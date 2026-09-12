# DB Subnet Group (Using Default VPC Subnets across availability zones)
resource "aws_db_subnet_group" "rds" {
  name        = "${var.app_name}-db-subnet-group"
  description = "Subnet group for ${var.app_name} RDS MySQL"
  subnet_ids  = data.aws_subnets.default.ids

  tags = {
    Name = "${var.app_name}-db-subnet-group"
  }
}

# RDS MySQL Security Group
resource "aws_security_group" "rds_mysql" {
  name        = "${var.app_name}-rds-mysql-sg"
  description = "Security group for ${var.app_name} RDS MySQL database"
  vpc_id      = data.aws_vpc.default.id

  # MySQL Ingress from ECS Backend Container
  ingress {
    description     = "MySQL 3306 from ECS Backend"
    from_port       = 3306
    to_port         = 3306
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs.id]
  }

  # MySQL Ingress for Admin Data Migration & Tooling
  ingress {
    description = "MySQL 3306 for Admin Migration and Diagnostics"
    from_port   = 3306
    to_port     = 3306
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "Allow all outbound traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.app_name}-rds-mysql-sg"
  }
}

# AWS RDS MySQL 8.0 Instance
resource "aws_db_instance" "mysql" {
  identifier                  = "${var.app_name}-mysql"
  engine                      = "mysql"
  engine_version              = "8.0"
  instance_class              = "db.t4g.micro"
  allocated_storage           = 20
  max_allocated_storage       = 50
  storage_type                = "gp3"
  storage_encrypted           = false
  publicly_accessible         = true
  apply_immediately           = true
  skip_final_snapshot         = true
  deletion_protection         = false

  db_name                     = var.db_name
  username                    = var.db_user
  password                    = var.db_password
  port                        = 3306

  db_subnet_group_name        = aws_db_subnet_group.rds.name
  vpc_security_group_ids      = [aws_security_group.rds_mysql.id]
  parameter_group_name        = "default.mysql8.0"

  tags = {
    Name = "${var.app_name}-mysql"
  }
}
