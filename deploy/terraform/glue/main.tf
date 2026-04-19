variable "env"            { type = string }
variable "region"         { type = string }
variable "otel_bucket"    { type = string }

locals {
  glue_db = replace("formica_otel_${var.env}_${var.region}", "-", "_")
}

resource "aws_glue_catalog_database" "otel" {
  name = local.glue_db
}

# ---- Traces ----

resource "aws_glue_catalog_table" "traces" {
  name          = "traces"
  database_name = aws_glue_catalog_database.otel.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    "classification"         = "parquet"
    "projection.enabled"     = "true"
    "projection.year.type"   = "integer"
    "projection.year.range"  = "2024,2100"
    "projection.month.type"  = "integer"
    "projection.month.range" = "1,12"
    "projection.day.type"    = "integer"
    "projection.day.range"   = "1,31"
    "projection.hour.type"   = "integer"
    "projection.hour.range"  = "0,23"
    "storage.location.template" =
      "s3://${var.otel_bucket}/year=$${year}/month=$${month}/day=$${day}/hour=$${hour}/traces/"
  }

  partition_keys {
    name = "year"
    type = "int"
  }
  partition_keys {
    name = "month"
    type = "int"
  }
  partition_keys {
    name = "day"
    type = "int"
  }
  partition_keys {
    name = "hour"
    type = "int"
  }

  storage_descriptor {
    location      = "s3://${var.otel_bucket}/traces/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
    }

    columns {
      name = "trace_id" type = "string"
    }
    columns {
      name = "span_id" type = "string"
    }
    columns {
      name = "parent_span_id" type = "string"
    }
    columns {
      name = "name" type = "string"
    }
    columns {
      name = "kind" type = "string"
    }
    columns {
      name = "start_time_unix_nano" type = "bigint"
    }
    columns {
      name = "end_time_unix_nano" type = "bigint"
    }
    columns {
      name = "status_code" type = "string"
    }
    columns {
      name = "attributes" type = "string"
    }
    columns {
      name = "resource" type = "string"
    }
  }
}

# ---- Metrics ----

resource "aws_glue_catalog_table" "metrics" {
  name          = "metrics"
  database_name = aws_glue_catalog_database.otel.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    "classification" = "parquet"
  }

  storage_descriptor {
    location      = "s3://${var.otel_bucket}/metrics/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"
    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
    }
    columns { name = "name" type = "string" }
    columns { name = "unit" type = "string" }
    columns { name = "time_unix_nano" type = "bigint" }
    columns { name = "value_double" type = "double" }
    columns { name = "value_int" type = "bigint" }
    columns { name = "attributes" type = "string" }
    columns { name = "resource" type = "string" }
  }
}

# ---- Logs ----

resource "aws_glue_catalog_table" "logs" {
  name          = "logs"
  database_name = aws_glue_catalog_database.otel.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    "classification" = "parquet"
  }

  storage_descriptor {
    location      = "s3://${var.otel_bucket}/logs/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"
    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
    }
    columns { name = "time_unix_nano" type = "bigint" }
    columns { name = "severity_text" type = "string" }
    columns { name = "severity_number" type = "int" }
    columns { name = "body" type = "string" }
    columns { name = "trace_id" type = "string" }
    columns { name = "span_id" type = "string" }
    columns { name = "attributes" type = "string" }
    columns { name = "resource" type = "string" }
  }
}
