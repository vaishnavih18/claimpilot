locals {
  # Two images: the FastAPI app (agent + GraphQL API) and the MCP server.
  # Matches the two things in app/ that actually get containerized and
  # deployed to EKS — app/agent + app/api together as one image, and
  # app/mcp_server as a separate one, since they're separate deployments.
  ecr_repositories = ["api", "mcp-server"]
}

resource "aws_ecr_repository" "main" {
  for_each = toset(local.ecr_repositories)

  name                 = "${var.project_name}/${each.value}"
  image_tag_mutability = "IMMUTABLE"
  # IMMUTABLE, not MUTABLE: once a tag like "v3" is pushed, it can't be
  # overwritten by a later push with the same tag. This is what makes a tag
  # trustworthy for a Kubernetes deployment - "v3" always means the exact
  # same image. MUTABLE would let a later `docker push` silently replace
  # what "v3" points to, which is how you get "it worked on my machine but
  # the cluster is running something different" bugs.
  #
  # When to change: never, really, for this project. MUTABLE only makes
  # sense for a tag like "latest" that's meant to float - not how we're
  # deploying here.

  image_scanning_configuration {
    scan_on_push = true
    # Free vulnerability scanning on every push (basic scanning, no extra
    # cost) - catches known CVEs in base images before they reach EKS.
  }

  tags = {
    Name = "${var.project_name}-ecr-${each.value}"
  }
}

resource "aws_ecr_lifecycle_policy" "main" {
  for_each   = aws_ecr_repository.main
  repository = each.value.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Expire untagged images after 7 days"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 7
        }
        action = { type = "expire" }
      }
    ]
  })
  # Only cleans up UNTAGGED images (leftovers from a build that got
  # superseded before anything referenced it) - every tagged image is kept
  # forever, since IMMUTABLE tags mean a tag is a permanent, meaningful
  # pointer, not clutter. 7 days is arbitrary but generous for a 3-day
  # project; AWS also charges a small amount per GB-month stored, so this is
  # just basic hygiene, not a hard requirement at this scale.
  #
  # When to change: bump countNumber down (e.g. to 1) if build iteration
  # during the day is producing a lot of untagged images and storage starts
  # to matter; irrelevant for a cleanup running once a week.
}
