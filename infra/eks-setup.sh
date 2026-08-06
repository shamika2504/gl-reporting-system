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
  eksctl create cluster \
    --name "$CLUSTER_NAME" \
    --region "$REGION" \
    --nodegroup-name gl-reporting-nodes \
    --node-type t3.medium \
    --nodes 1 \
    --nodes-min 1 \
    --nodes-max 3 \
    --managed \
    --with-oidc

  aws eks update-kubeconfig --name "$CLUSTER_NAME" --region "$REGION"
  kubectl get nodes
}

# AWS Load Balancer Controller, so k8s/ingress.yaml (class: alb) provisions a
# real ALB in front of the backend Service.
section_alb_controller() {
  eksctl utils associate-iam-oidc-provider --cluster "$CLUSTER_NAME" --region "$REGION" --approve

  curl -sL -o /tmp/alb-iam-policy.json \
    https://raw.githubusercontent.com/kubernetes-sigs/aws-load-balancer-controller/v2.9.0/docs/install/iam_policy.json

  aws iam create-policy \
    --policy-name AWSLoadBalancerControllerIAMPolicy \
    --policy-document file:///tmp/alb-iam-policy.json || echo "Policy may already exist — continuing."

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
