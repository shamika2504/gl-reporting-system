# GL Regulatory Reporting System

This repository contains a GL regulatory reporting system built with FastAPI, PostgreSQL, pgvector, Qdrant, Celery, Redis, AWS S3, and Anthropic Claude. It aggregates general ledger data into financial statements, detects anomalies, generates LLM-authored narrative commentary grounded in retrieved GAAP rules, and renders the result as an audit-ready PDF.

## Structure

- backend/ for the FastAPI application and worker services
- scripts/ for database initialization, synthetic data seeding, and GAAP rule embedding
- infra/ for AWS resource provisioning scripts (RDS, ElastiCache, S3, ECR, Secrets Manager, EKS)
- k8s/ for the Kubernetes manifests deployed to EKS
- .github/workflows/ for the CI/CD pipeline
- docker-compose.yml for local development infrastructure

## Getting started (local)

1. Copy .env.example to .env and adjust values.
2. Run docker-compose up.
3. Visit http://localhost:8000/health for the service health endpoint.

## Deploying to AWS

Production runs on EKS, with images built by GitHub Actions and pushed to ECR. Nothing is hardcoded — application secrets are synced from AWS Secrets Manager via the External Secrets Operator, and CI authenticates to AWS over OIDC (no long-lived access keys).

### 1. Provision AWS resources

Run each section of `infra/aws-setup.sh` in order, filling in the VPC/subnet-group placeholders for your account:

```bash
bash infra/aws-setup.sh rds          # RDS Postgres 15 (db.t3.micro) + pgvector
bash infra/aws-setup.sh redis        # ElastiCache Redis (cache.t3.micro)
bash infra/aws-setup.sh s3           # gl-reporting-reports-<account-id>, private, versioned
bash infra/aws-setup.sh ecr          # gl-reporting-backend repository
DB_ENDPOINT=... DB_PASSWORD=... REDIS_ENDPOINT=... \
  bash infra/aws-setup.sh secrets    # writes gl-reporting/prod to Secrets Manager
GITHUB_REPO=<org>/<repo> \
  bash infra/aws-setup.sh github-oidc  # GitHub Actions OIDC provider + deploy role
```

After the `secrets` step, replace the `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` placeholders with real values (see the script's output for the exact `put-secret-value` command).

Store the role ARN printed by the `github-oidc` step as the `AWS_DEPLOY_ROLE_ARN` secret in the GitHub repo settings.

### 2. Create the EKS cluster and cluster add-ons

```bash
bash infra/eks-setup.sh cluster              # eksctl-managed EKS cluster, t3.medium, 1-3 nodes
bash infra/eks-setup.sh alb-controller       # AWS Load Balancer Controller, for k8s/ingress.yaml
bash infra/eks-setup.sh external-secrets     # External Secrets Operator, for k8s/secrets.yaml
bash infra/eks-setup.sh app-service-account  # scoped IRSA role for backend/worker pod S3 access
```

Then grant the GitHub Actions deploy role access to the cluster (also printed by `aws-setup.sh github-oidc`):

```bash
aws eks create-access-entry --cluster-name gl-reporting-cluster \
  --principal-arn <role-arn> --type STANDARD --region us-east-1
aws eks associate-access-policy --cluster-name gl-reporting-cluster \
  --principal-arn <role-arn> --access-scope type=cluster \
  --policy-arn arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy --region us-east-1
```

### 3. Deploy

Push to `main`. `.github/workflows/deploy.yml` builds the image, pushes it to ECR tagged with the commit SHA, applies `k8s/`, waits for both the `backend` and `worker` rollouts, and health-checks the ALB's `/health` endpoint before finishing.

The backend and worker deployments share the same image (`k8s/backend-deployment.yaml`, `k8s/worker-deployment.yaml`) — only the container `command` differs (`uvicorn` vs `celery worker`).

### Rollback

If a deploy goes bad, roll the affected deployment back to its previous revision:

```bash
kubectl rollout undo deployment/backend -n gl-reporting
kubectl rollout undo deployment/worker -n gl-reporting
```

To go back further than one revision, check `kubectl rollout history deployment/backend -n gl-reporting` and target a specific one with `--to-revision=<N>`.
