#!/usr/bin/env bash
# EKS cluster + cluster-side add-ons for the GL Regulatory Reporting System.
# Run after infra/aws-setup.sh has provisioned RDS/ElastiCache/S3/ECR/Secrets Manager.
#
# Requires: eksctl, kubectl, helm.
#
# Usage:
#   bash infra/eks-setup.sh cluster
#   bash infra/eks-setup.sh alb-controller
#   bash infra/eks-setup.sh external-secrets

set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
CLUSTER_NAME="gl-reporting-cluster"

section_cluster() {
  # Pin the cluster to the account's default VPC — the same one
  # infra/aws-setup.sh provisions RDS/ElastiCache into. Without this, eksctl
  # creates a brand-new, unpeered VPC and the cluster's pods can never reach
  # RDS/Redis at all (not a security-group problem, a routability one).
  local vpc_id subnet_ids
  vpc_id="$(aws ec2 describe-vpcs \
    --filters "Name=isDefault,Values=true" \
    --query "Vpcs[0].VpcId" \
    --output text --region "$REGION")"
  # us-east-1e (and its equivalent in some other accounts/regions) doesn't
  # support EKS control plane instances in every account — exclude it rather
  # than let cluster creation fail partway through a CloudFormation rollback.
  subnet_ids="$(aws ec2 describe-subnets \
    --filters "Name=vpc-id,Values=$vpc_id" "Name=availability-zone,Values=us-east-1a,us-east-1b,us-east-1c,us-east-1d,us-east-1f" \
    --query "Subnets[*].SubnetId" \
    --output text --region "$REGION" | tr '\t' ',')"

  echo "Creating cluster in default VPC $vpc_id, subnets [$subnet_ids]"

  # eksctl only auto-tags subnets it creates itself in a brand-new VPC. Since
  # we're pointing it at pre-existing default-VPC subnets, tag them by hand —
  # the AWS Load Balancer Controller needs kubernetes.io/role/elb to place an
  # internet-facing ALB without falling back to a route-table-reachability
  # discovery path that the controller's own IAM policy doesn't grant.
  IFS=',' read -ra subnet_array <<< "$subnet_ids"
  for subnet in "${subnet_array[@]}"; do
    aws ec2 create-tags --resources "$subnet" --region "$REGION" --tags \
      "Key=kubernetes.io/cluster/${CLUSTER_NAME},Value=shared" \
      "Key=kubernetes.io/role/elb,Value=1"
  done

  eksctl create cluster \
    --name "$CLUSTER_NAME" \
    --region "$REGION" \
    --vpc-public-subnets "$subnet_ids" \
    --nodegroup-name gl-reporting-nodes \
    --node-type t3.medium \
    --nodes 1 \
    --nodes-min 1 \
    --nodes-max 3 \
    --managed \
    --with-oidc

  aws eks update-kubeconfig --name "$CLUSTER_NAME" --region "$REGION"
  kubectl get nodes

  # Allow the cluster's node/pod security group to reach RDS (5432) and
  # Redis (6379), which otherwise only allow traffic from their own SG.
  local node_sg rds_sg redis_sg
  node_sg="$(aws eks describe-cluster --name "$CLUSTER_NAME" --region "$REGION" \
    --query 'cluster.resourcesVpcConfig.clusterSecurityGroupId' --output text)"
  rds_sg="$(aws rds describe-db-instances --db-instance-identifier gl-reporting-db --region "$REGION" \
    --query 'DBInstances[0].VpcSecurityGroups[0].VpcSecurityGroupId' --output text)"
  redis_sg="$(aws elasticache describe-cache-clusters --cache-cluster-id gl-reporting-redis --region "$REGION" \
    --query 'CacheClusters[0].SecurityGroups[0].SecurityGroupId' --output text)"

  aws ec2 authorize-security-group-ingress --group-id "$rds_sg" --protocol tcp --port 5432 \
    --source-group "$node_sg" --region "$REGION" || echo "RDS ingress rule may already exist — continuing."
  aws ec2 authorize-security-group-ingress --group-id "$redis_sg" --protocol tcp --port 6379 \
    --source-group "$node_sg" --region "$REGION" || echo "Redis ingress rule may already exist — continuing."
}

# AWS Load Balancer Controller, so k8s/ingress.yaml (class: alb) provisions a
# real ALB in front of the backend Service.
section_alb_controller() {
  eksctl utils associate-iam-oidc-provider --cluster "$CLUSTER_NAME" --region "$REGION" --approve

  curl -sL -o /tmp/alb-iam-policy.json \
    https://raw.githubusercontent.com/kubernetes-sigs/aws-load-balancer-controller/v2.9.0/docs/install/iam_policy.json

  # The published v2.9.0 policy is missing ec2:DescribeRouteTables, which the
  # controller needs for its subnet-reachability discovery fallback — without
  # it, Ingress reconciliation fails with a 403 and the ALB never gets created.
  python3 -c "
import json
with open('/tmp/alb-iam-policy.json') as f:
    doc = json.load(f)
for stmt in doc['Statement']:
    actions = stmt.get('Action', [])
    if isinstance(actions, list) and 'ec2:DescribeSubnets' in actions and 'ec2:DescribeRouteTables' not in actions:
        actions.append('ec2:DescribeRouteTables')
with open('/tmp/alb-iam-policy.json', 'w') as f:
    json.dump(doc, f, indent=2)
"

  if aws iam get-policy --policy-arn "arn:aws:iam::${ACCOUNT_ID}:policy/AWSLoadBalancerControllerIAMPolicy" >/dev/null 2>&1; then
    aws iam create-policy-version \
      --policy-arn "arn:aws:iam::${ACCOUNT_ID}:policy/AWSLoadBalancerControllerIAMPolicy" \
      --policy-document file:///tmp/alb-iam-policy.json \
      --set-as-default
  else
    aws iam create-policy \
      --policy-name AWSLoadBalancerControllerIAMPolicy \
      --policy-document file:///tmp/alb-iam-policy.json
  fi

  eksctl create iamserviceaccount \
    --cluster "$CLUSTER_NAME" \
    --namespace kube-system \
    --name aws-load-balancer-controller \
    --role-name AmazonEKSLoadBalancerControllerRole \
    --attach-policy-arn "arn:aws:iam::${ACCOUNT_ID}:policy/AWSLoadBalancerControllerIAMPolicy" \
    --region "$REGION" \
    --approve

  helm repo add eks https://aws.github.io/eks-charts
  helm repo update

  helm install aws-load-balancer-controller eks/aws-load-balancer-controller \
    -n kube-system \
    --set clusterName="$CLUSTER_NAME" \
    --set serviceAccount.create=false \
    --set serviceAccount.name=aws-load-balancer-controller

  kubectl rollout status deployment/aws-load-balancer-controller -n kube-system
}

# External Secrets Operator, so k8s/secrets.yaml can sync the app secret out
# of AWS Secrets Manager into a native k8s Secret.
#
# The operator itself runs in the "external-secrets" namespace, but the
# ServiceAccount used for IRSA auth lives in "gl-reporting" (where
# k8s/secrets.yaml's SecretStore references it) — scoped to just that
# namespace/name pair, not the operator's own service account.
section_external_secrets() {
  kubectl create namespace gl-reporting --dry-run=client -o yaml | kubectl apply -f -

  eksctl create iamserviceaccount \
    --cluster "$CLUSTER_NAME" \
    --namespace gl-reporting \
    --name external-secrets-sa \
    --attach-policy-arn arn:aws:iam::aws:policy/SecretsManagerReadWrite \
    --region "$REGION" \
    --approve \
    --override-existing-serviceaccounts

  helm repo add external-secrets https://charts.external-secrets.io
  helm repo update

  helm install external-secrets external-secrets/external-secrets \
    -n external-secrets \
    --create-namespace

  kubectl rollout status deployment/external-secrets -n external-secrets
}

# Runtime IAM identity for the backend/worker pods themselves — scoped to
# just the reports bucket, so boto3 in s3_service.py picks up pod credentials
# via IRSA instead of needing AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY at all.
section_app_service_account() {
  local bucket="gl-reporting-reports-${ACCOUNT_ID}"

  cat > /tmp/gl-reporting-app-s3-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject"],
      "Resource": "arn:aws:s3:::${bucket}/reports/*"
    }
  ]
}
EOF

  aws iam create-policy \
    --policy-name GLReportingAppS3Policy \
    --policy-document file:///tmp/gl-reporting-app-s3-policy.json || echo "Policy may already exist — continuing."

  kubectl create namespace gl-reporting --dry-run=client -o yaml | kubectl apply -f -

  eksctl create iamserviceaccount \
    --cluster "$CLUSTER_NAME" \
    --namespace gl-reporting \
    --name gl-reporting-app-sa \
    --attach-policy-arn "arn:aws:iam::${ACCOUNT_ID}:policy/GLReportingAppS3Policy" \
    --region "$REGION" \
    --approve \
    --override-existing-serviceaccounts
}

case "${1:-}" in
  cluster) section_cluster ;;
  alb-controller) section_alb_controller ;;
  external-secrets) section_external_secrets ;;
  app-service-account) section_app_service_account ;;
  *)
    echo "Usage: $0 {cluster|alb-controller|external-secrets|app-service-account}"
    exit 1
    ;;
esac
