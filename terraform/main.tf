# Root module -- composes networking, RDS, secrets, and ECS for one
# environment. One workspace (one state file, keyed by env_id) per
# environment; see backend.tf.

locals {
  common_tags = {
    env_id     = var.env_id
    env_name   = var.env_name
    team       = var.team
    env_type   = var.env_type
    ttl_hours  = tostring(var.ttl_hours)
    managed_by = "idp-lite"
  }
}

module "networking" {
  source = "./modules/networking"

  env_id      = var.env_id
  vpc_id      = var.vpc_id
  region      = var.region
  common_tags = local.common_tags
}

module "rds" {
  source = "./modules/rds"

  env_id             = var.env_id
  subnet_ids         = module.networking.subnet_ids
  security_group_id  = module.networking.security_group_id
  common_tags        = local.common_tags
}

module "secrets" {
  source = "./modules/secrets"

  env_id       = var.env_id
  rds_address  = module.rds.address
  rds_port     = 5432
  rds_username = module.rds.username
  rds_password = module.rds.password
  common_tags  = local.common_tags
}

module "ecs" {
  source = "./modules/ecs"

  env_id             = var.env_id
  region             = var.region
  subnet_id          = module.networking.subnet_id
  security_group_id  = module.networking.security_group_id
  rds_secret_arn     = module.secrets.secret_arn
  container_image    = var.container_image
  common_tags        = local.common_tags
}
