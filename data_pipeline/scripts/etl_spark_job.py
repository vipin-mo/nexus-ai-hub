import os
import sys
from datetime import datetime
from pyspark.sql import SparkSession
from pyspark.sql.functions import col, when, count, avg
import duckdb

# Determine file system directory parameters targeting analytical warehouses
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_JSON_PATH = os.path.normpath(os.path.join(SCRIPT_DIR, "../storage/sanitized_log.json"))
ANALYTICS_DB_PATH = os.path.normpath(os.path.join(SCRIPT_DIR, "../../ui_analytics/analytics_warehouse.db"))

def run_big_data_etl_pipeline():
    print(f"⚡ [{datetime.now()}] Initializing High-Throughput PySpark Data Pipeline Engine...")

    # 1. Instantiate local isolated single-node Spark Context session configuration
    spark = SparkSession.builder \
        .appName("NexusAI_Log_Analytics_ETL") \
        .master("local[*]") \
        .config("spark.driver.memory", "1g") \
        .getOrCreate()

    # Check if the Perl script has generated the sanitized target source log file
    if not os.path.exists(INPUT_JSON_PATH):
        print(f"🛑 [ETL Error] Source file missing at {INPUT_JSON_PATH}. Run parser.pl execution steps first.")
        spark.stop()
        return

    try:
        # 2. Extract: Read structured JSON arrays safely into a Spark DataFrame
        print(f"Extracting records natively from data source: {INPUT_JSON_PATH}")
        df = spark.read.option("multiline", "true").json(INPUT_JSON_PATH)

        # Handle empty dataset context definitions seamlessly without dropping threads
        if df.rdd.isEmpty():
            print("⚠️ [ETL Job Warning] Empty structural framework discovered inside source target array. Aborting pipeline loops.")
            spark.stop()
            return

        # 3. Transform: Apply analytical aggregations over system metadata matrix tracking columns
        print("Executing operational transformations and safety rule validation passes...")

        metrics_df = df.agg(
            count("timestamp").alias("total_logs_processed"),
            avg(when(col("level") == "ERROR", 1).otherwise(0)).alias("error_rate_ratio")
        )

        # Extract row objects safely to prevent TypeCasting crashes on empty data pools
        summary_row = metrics_df.collect()[0]
        total_logs = summary_row["total_logs_processed"] or 0
        error_rate = summary_row["error_rate_ratio"] if summary_row["error_rate_ratio"] is not None else 0.0

        # 4. Load: Connect to localized analytical datastores and upsert analytics
        print(f"Loading structured telemetry indicators into analytics database: {ANALYTICS_DB_PATH}")
        ctx = duckdb.connect(ANALYTICS_DB_PATH)

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
        print(f"📊 [ETL Job Complete] Successfully synchronized {total_logs} elements. Calculated error ratio: {error_rate * 100:.2f}%")

    except Exception as e:
        print(f"❌ [ETL Processing Failure] Internal pipeline runtime exception discovered: {str(e)}")

    finally:
        # Guarantee memory cleanup step sequence runs cleanly on the local workspace node
        spark.stop()

if __name__ == "__main__":
    run_big_data_etl_pipeline()
