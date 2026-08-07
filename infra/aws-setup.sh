#!/usr/bin/env bash
# AWS infrastructure setup for the GL Regulatory Reporting System.
#
# VPC, subnets, and the security group are auto-detected from the account's
# default VPC; the DB/cache subnet groups are created automatically in their
# respective sections. Override any of VPC_ID / SUBNET_IDS /
# VPC_SECURITY_GROUP_ID by exporting them first if you're not using the
# default VPC. Requires: aws-cli v2, a configured `aws` profile with
# admin-ish permissions, and psql for the pgvector step.
#
# Usage: source the sections you need, e.g.
#   bash infra/aws-setup.sh rds
#   bash infra/aws-setup.sh redis
#   bash infra/aws-setup.sh s3
#   bash infra/aws-setup.sh ecr
#   bash infra/aws-setup.sh secrets
#   bash infra/aws-setup.sh github-oidc

set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"

DB_INSTANCE_ID="gl-reporting-db"
DB_NAME="gl_reporting"
DB_MASTER_USER="gl_admin"
REDIS_CLUSTER_ID="gl-reporting-redis"
S3_BUCKET="gl-reporting-reports-${ACCOUNT_ID}"
ECR_REPO="gl-reporting-backend"
SECRET_ID="gl-reporting/prod"
EKS_CLUSTER_NAME="gl-reporting-cluster"
GITHUB_REPO="${GITHUB_REPO:-shamika2504/gl-reporting-system}"

# Auto-detected from the account's default VPC. Override any of these by
# exporting the env var before invoking the script if you're not using the
# default VPC.
VPC_ID="${VPC_ID:-$(aws ec2 describe-vpcs \
  --filters "Name=isDefault,Values=true" \
  --query "Vpcs[0].VpcId" \
  --output text --region "$REGION")}"

if [ -z "$VPC_ID" ] || [ "$VPC_ID" = "None" ]; then
  echo "No default VPC found in $REGION — set VPC_ID explicitly." >&2
  exit 1
fi

SUBNET_IDS="${SUBNET_IDS:-$(aws ec2 describe-subnets \
  --filters "Name=vpc-id,Values=$VPC_ID" \
  --query "Subnets[*].SubnetId" \
  --output text --region "$REGION" | tr '\t' ',')}"

VPC_SECURITY_GROUP_ID="${VPC_SECURITY_GROUP_ID:-$(aws ec2 describe-security-groups \
  --filters "Name=vpc-id,Values=$VPC_ID" "Name=group-name,Values=default" \
  --query "SecurityGroups[0].GroupId" \
  --output text --region "$REGION")}"

DB_SUBNET_GROUP_NAME="${DB_SUBNET_GROUP_NAME:-gl-reporting-db-subnet}"
CACHE_SUBNET_GROUP_NAME="${CACHE_SUBNET_GROUP_NAME:-gl-reporting-cache-subnet}"

section_rds() {
  echo "Using VPC $VPC_ID, subnets [$SUBNET_IDS], security group $VPC_SECURITY_GROUP_ID"

  aws rds create-db-subnet-group \
    --db-subnet-group-name "$DB_SUBNET_GROUP_NAME" \
    --db-subnet-group-description "GL Reporting DB Subnet Group" \
    --subnet-ids $(echo "$SUBNET_IDS" | tr ',' ' ') \
    --region "$REGION" || echo "DB subnet group may already exist — continuing."

  local db_password
  # RDS master passwords can't contain '/', '@', '"', or spaces; openssl
  # rand -hex only ever produces [0-9a-f], and (unlike `tr < /dev/urandom |
  # head -c N`) doesn't SIGPIPE itself when the reader closes early, which
  # would otherwise abort the script under `set -o pipefail`.
  db_password="$(openssl rand -hex 24)"

  aws rds create-db-instance \
    --db-instance-identifier "$DB_INSTANCE_ID" \
    --db-instance-class db.t3.micro \
    --engine postgres \
    --engine-version 15.7 \
    --allocated-storage 20 \
    --db-name "$DB_NAME" \
    --master-username "$DB_MASTER_USER" \
    --master-user-password "$db_password" \
    --vpc-security-group-ids "$VPC_SECURITY_GROUP_ID" \
    --db-subnet-group-name "$DB_SUBNET_GROUP_NAME" \
    --backup-retention-period 7 \
    --storage-encrypted \
    --no-publicly-accessible \
    --region "$REGION"

  echo "Waiting for $DB_INSTANCE_ID to become available (this takes several minutes)..."
  aws rds wait db-instance-available --db-instance-identifier "$DB_INSTANCE_ID" --region "$REGION"

  local db_endpoint
  db_endpoint="$(aws rds describe-db-instances \
    --db-instance-identifier "$DB_INSTANCE_ID" \
    --query 'DBInstances[0].Endpoint.Address' --output text --region "$REGION")"

  echo "RDS endpoint: $db_endpoint"
  echo "Enabling pgvector extension..."
  PGPASSWORD="$db_password" psql -h "$db_endpoint" -U "$DB_MASTER_USER" -d "$DB_NAME" \
    -c "CREATE EXTENSION IF NOT EXISTS vector;"

  echo "DB_ENDPOINT=$db_endpoint"
  echo "DB_PASSWORD=$db_password"
  echo "(save these — you'll need them for the 'secrets' section below)"
}

section_redis() {
  echo "Using VPC $VPC_ID, subnets [$SUBNET_IDS], security group $VPC_SECURITY_GROUP_ID"

  aws elasticache create-cache-subnet-group \
    --cache-subnet-group-name "$CACHE_SUBNET_GROUP_NAME" \
    --cache-subnet-group-description "GL Reporting Cache Subnet" \
    --subnet-ids $(echo "$SUBNET_IDS" | tr ',' ' ') \
    --region "$REGION" || echo "Cache subnet group may already exist — continuing."

  aws elasticache create-cache-cluster \
    --cache-cluster-id "$REDIS_CLUSTER_ID" \
    --cache-node-type cache.t3.micro \
    --engine redis \
    --num-cache-nodes 1 \
    --cache-subnet-group-name "$CACHE_SUBNET_GROUP_NAME" \
    --security-group-ids "$VPC_SECURITY_GROUP_ID" \
    --region "$REGION"

  echo "Waiting for $REDIS_CLUSTER_ID to become available..."
  aws elasticache wait cache-cluster-available --cache-cluster-id "$REDIS_CLUSTER_ID" --region "$REGION"

  local redis_endpoint
  redis_endpoint="$(aws elasticache describe-cache-clusters \
    --cache-cluster-id "$REDIS_CLUSTER_ID" --show-cache-node-info \
    --query 'CacheClusters[0].CacheNodes[0].Endpoint.Address' --output text --region "$REGION")"

  echo "REDIS_ENDPOINT=$redis_endpoint"
}

section_s3() {
  if [ "$REGION" = "us-east-1" ]; then
    aws s3api create-bucket --bucket "$S3_BUCKET" --region "$REGION"
  else
    aws s3api create-bucket --bucket "$S3_BUCKET" --region "$REGION" \
      --create-bucket-configuration LocationConstraint="$REGION"
  fi

  aws s3api put-public-access-block \
    --bucket "$S3_BUCKET" \
    --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

  aws s3api put-bucket-versioning \
    --bucket "$S3_BUCKET" \
    --versioning-configuration Status=Enabled

  echo "S3_BUCKET=$S3_BUCKET"
}

section_ecr() {
  aws ecr create-repository \
    --repository-name "$ECR_REPO" \
    --image-scanning-configuration scanOnPush=true \
    --region "$REGION"

  echo "ECR_REPOSITORY_URI=${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${ECR_REPO}"
}

# Run after rds/redis/s3. DB_ENDPOINT is looked up from RDS automatically if
# not passed in; DB_PASSWORD can't be recovered after creation (RDS doesn't
# expose it), so that one still has to come from the rds step's output.
# Usage: DB_PASSWORD=... REDIS_ENDPOINT=... bash infra/aws-setup.sh secrets
section_secrets() {
  if [ -z "${DB_ENDPOINT:-}" ]; then
    DB_ENDPOINT="$(aws rds describe-db-instances \
      --db-instance-identifier "$DB_INSTANCE_ID" \
      --query 'DBInstances[0].Endpoint.Address' --output text --region "$REGION" 2>/dev/null || true)"
  fi
  DB_ENDPOINT="${DB_ENDPOINT:-placeholder-update-after-rds}"
  [ "$DB_ENDPOINT" = "placeholder-update-after-rds" ] && \
    echo "Warning: could not resolve the RDS endpoint — writing a placeholder. Re-run with DB_ENDPOINT set once the instance exists." >&2

  : "${DB_PASSWORD:?set DB_PASSWORD from the rds step}"
  : "${REDIS_ENDPOINT:?set REDIS_ENDPOINT from the redis step}"

  aws secretsmanager create-secret \
    --name "$SECRET_ID" \
    --description "GL Reporting System application secrets" \
    --secret-string "$(cat <<JSON
{
  "DB_URL": "postgres://${DB_MASTER_USER}:${DB_PASSWORD}@${DB_ENDPOINT}:5432/${DB_NAME}",
  "REDIS_URL": "redis://${REDIS_ENDPOINT}:6379/0",
  "ANTHROPIC_API_KEY": "replace-me",
  "OPENAI_API_KEY": "replace-me",
  "LANGCHAIN_API_KEY": "replace-me",
  "LANGCHAIN_TRACING_V2": "false",
  "LANGCHAIN_PROJECT": "gl-reporting-prod",
  "S3_BUCKET_NAME": "${S3_BUCKET}"
}
JSON
)" \
    --region "$REGION"

  echo "Secret created at $SECRET_ID."
  echo "Replace the placeholder keys with real values using a read-modify-write (see README's Secrets Manager section) — put-secret-value replaces the whole blob, so don't overwrite it with a partial JSON file."
}

# GitHub Actions -> AWS auth via OIDC (no long-lived access keys).
# Defaults to GITHUB_REPO above; override by exporting GITHUB_REPO=org/repo.
section_github_oidc() {
  echo "Using GITHUB_REPO=$GITHUB_REPO"

  # GitHub's documented OIDC thumbprint; AWS validates against the IdP's live
  # TLS chain, so this value mostly satisfies the API's required parameter.
  aws iam create-open-id-connect-provider \
    --url https://token.actions.githubusercontent.com \
    --client-id-list sts.amazonaws.com \
    --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1 \
    --region "$REGION" || echo "OIDC provider may already exist — continuing."

  cat > /tmp/gl-reporting-github-trust-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::${ACCOUNT_ID}:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
        },
        "StringLike": {
          "token.actions.githubusercontent.com:sub": "repo:${GITHUB_REPO}:ref:refs/heads/main"
        }
      }
    }
  ]
}
EOF

  aws iam create-role \
    --role-name gl-reporting-github-actions \
    --assume-role-policy-document file:///tmp/gl-reporting-github-trust-policy.json

  # ECR push access. Scope this down to the single repo ARN for production.
  aws iam attach-role-policy \
    --role-name gl-reporting-github-actions \
    --policy-arn arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryPowerUser

  # eks:DescribeCluster — required for `aws eks update-kubeconfig` in the
  # deploy workflow to even fetch cluster connection info. This is a plain
  # IAM permission, separate from (and a prerequisite for) the EKS access
  # entry granted below, which only governs in-cluster Kubernetes RBAC once
  # the role can already reach the control plane API.
  cat > /tmp/gl-reporting-eks-describe-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["eks:DescribeCluster"],
      "Resource": "arn:aws:eks:${REGION}:${ACCOUNT_ID}:cluster/${EKS_CLUSTER_NAME}"
    }
  ]
}
EOF
  aws iam create-policy \
    --policy-name GLReportingEKSDescribePolicy \
    --policy-document file:///tmp/gl-reporting-eks-describe-policy.json \
    --region "$REGION" || echo "Policy may already exist — continuing."

  aws iam attach-role-policy \
    --role-name gl-reporting-github-actions \
    --policy-arn "arn:aws:iam::${ACCOUNT_ID}:policy/GLReportingEKSDescribePolicy"

  echo "Role ARN: arn:aws:iam::${ACCOUNT_ID}:role/gl-reporting-github-actions"
  echo "Store this as the AWS_DEPLOY_ROLE_ARN secret in the GitHub repo."
  echo ""
  echo "After the EKS cluster exists, grant this role cluster access:"
  cat <<EOM
  aws eks create-access-entry \\
    --cluster-name $EKS_CLUSTER_NAME \\
    --principal-arn arn:aws:iam::${ACCOUNT_ID}:role/gl-reporting-github-actions \\
    --type STANDARD \\
    --region $REGION

  aws eks associate-access-policy \\
    --cluster-name $EKS_CLUSTER_NAME \\
    --principal-arn arn:aws:iam::${ACCOUNT_ID}:role/gl-reporting-github-actions \\
    --access-scope type=cluster \\
    --policy-arn arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy \\
    --region $REGION
EOM
}

case "${1:-}" in
  rds) section_rds ;;
  redis) section_redis ;;
  s3) section_s3 ;;
  ecr) section_ecr ;;
  secrets) section_secrets ;;
  github-oidc) section_github_oidc ;;
  *)
    echo "Usage: $0 {rds|redis|s3|ecr|secrets|github-oidc}"
    exit 1
    ;;
esac
