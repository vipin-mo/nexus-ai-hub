import os
import json
from datetime import datetime
from pyspark.sql import SparkSession
from pyspark.sql.functions import col, when, count, avg
import duckdb

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_JSON_PATH = os.path.normpath(os.path.join(SCRIPT_DIR, "../storage/sanitized_log.json"))
ANALYTICS_DB_PATH = os.path.normpath(os.path.join(SCRIPT_DIR, "../../ui_analytics/analytics_warehouse.db"))

def run_big_data_etl_pipeline():
    print(f"⚡ [{datetime.now()}] Initializing PySpark Data Pipeline Engine...")

    if not os.path.exists(INPUT_JSON_PATH):
        print(f"🛑 [ETL Error] Source file missing at {INPUT_JSON_PATH}.")
        return

    # Validate JSON payload content prior to starting PySpark schema inference
    try:
        with open(INPUT_JSON_PATH, "r") as f:
            raw_data = json.load(f)
            if not raw_data:
                print("⚠️ [ETL Warning] Source JSON is empty ([ ]). Skipping execution.")
                return
    except Exception as e:
        print(f"🛑 [ETL Error] Invalid JSON formatting in source file: {e}")
        return

    spark = SparkSession.builder \
        .appName("NexusAI_Log_Analytics_ETL") \
        .master("local[*]") \
        .config("spark.driver.memory", "1g") \
        .getOrCreate()

    try:
        df = spark.read.option("multiline", "true").json(INPUT_JSON_PATH)

        metrics_df = df.agg(
            count("timestamp").alias("total_logs_processed"),
            avg(when(col("level") == "ERROR", 1).otherwise(0)).alias("error_rate_ratio")
        )

        summary_row = metrics_df.collect()[0]
        total_logs = summary_row["total_logs_processed"] or 0
        error_rate = summary_row["error_rate_ratio"] if summary_row["error_rate_ratio"] is not None else 0.0

        ctx = duckdb.connect(ANALYTICS_DB_PATH, read_only=False)

        ctx.execute("""
            CREATE TABLE IF NOT EXISTS platform_summary_metrics (
                run_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                total_records_analyzed INTEGER,
                calculated_error_ratio DOUBLE
            )
        """)

        ctx.execute("""
            INSERT INTO platform_summary_metrics (total_records_analyzed, calculated_error_ratio)
            VALUES (?, ?)
        """, (int(total_logs), float(error_rate)))

        ctx.close()
        print(f"📊 [ETL Job Complete] Processed {total_logs} records. Error ratio: {error_rate * 100:.2f}%")

    except Exception as e:
        print(f"❌ [ETL Processing Failure] Exception: {str(e)}")
    finally:
        spark.stop()

if __name__ == "__main__":
    run_big_data_etl_pipeline()