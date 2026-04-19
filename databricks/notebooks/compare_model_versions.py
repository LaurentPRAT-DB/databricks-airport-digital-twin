# Databricks notebook source
# MAGIC %md
# MAGIC # Model Version Comparison & Promotion
# MAGIC Compares all registered versions of turnaround and OBT models.
# MAGIC Selects the best version (lowest refined MAE) and promotes it with the "champion" alias.

# COMMAND ----------

%pip install mlflow --quiet

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

import json
import mlflow
from mlflow.tracking import MlflowClient

UC_CATALOG = "serverless_stable_3n0ihb_catalog"
UC_SCHEMA = "airport_digital_twin"

# All registered model names to compare
MODEL_GROUPS = {
    "turnaround": {
        "primary": f"{UC_CATALOG}.{UC_SCHEMA}.obt_refined_model",
        "coarse": f"{UC_CATALOG}.{UC_SCHEMA}.obt_coarse_model",
        "board": f"{UC_CATALOG}.{UC_SCHEMA}.obt_board_model",
        "primary_metric": "tpark_mae",  # lower is better
    },
    "obt_departure": {
        "primary": f"{UC_CATALOG}.{UC_SCHEMA}.obt_departure_refined_model",
        "coarse": f"{UC_CATALOG}.{UC_SCHEMA}.obt_departure_coarse_model",
        "primary_metric": "refined_mae",  # lower is better
    },
}

client = MlflowClient()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Collect All Model Versions & Metrics

# COMMAND ----------

results = {}

for group_name, group in MODEL_GROUPS.items():
    model_name = group["primary"]
    metric_key = group["primary_metric"]
    print(f"\n{'='*60}")
    print(f"Model group: {group_name}")
    print(f"Primary model: {model_name}")
    print(f"Comparison metric: {metric_key} (lower = better)")
    print(f"{'='*60}")

    try:
        versions = client.search_model_versions(f"name='{model_name}'")
    except Exception as e:
        print(f"WARNING: Could not list versions for {model_name}: {e}")
        continue

    if not versions:
        print(f"No versions found for {model_name}")
        continue

    group_results = []
    for v in sorted(versions, key=lambda x: int(x.version)):
        version = int(v.version)
        run_id = v.run_id
        aliases = v.aliases if hasattr(v, "aliases") else []

        # Get metrics from the MLflow run
        try:
            run = client.get_run(run_id)
            metrics = run.data.metrics
            params = run.data.params
        except Exception as e:
            print(f"  v{version}: could not fetch run {run_id}: {e}")
            continue

        mae = metrics.get(metric_key)
        n_files = params.get("n_simulation_files", "?")
        n_samples = params.get("n_train_samples", metrics.get("n_train_samples", "?"))

        entry = {
            "version": version,
            "run_id": run_id,
            "mae": mae,
            "n_files": n_files,
            "aliases": aliases,
            "metrics": {
                k: round(v, 4) if isinstance(v, float) else v
                for k, v in metrics.items()
                if not k.startswith("tpark_mae_") and not k.startswith("refined_mae_")
            },
        }
        group_results.append(entry)

        alias_str = f" [{', '.join(aliases)}]" if aliases else ""
        mae_str = f"{mae:.3f}" if mae is not None else "N/A"
        print(f"  v{version}: {metric_key}={mae_str}, files={n_files}, samples={n_samples}{alias_str}")

    results[group_name] = group_results

# COMMAND ----------

# MAGIC %md
# MAGIC ## Select Best Version & Promote

# COMMAND ----------

promotions = {}

for group_name, group in MODEL_GROUPS.items():
    group_results = results.get(group_name, [])
    if not group_results:
        print(f"\n{group_name}: no versions to compare")
        continue

    # Filter to versions that have the metric
    valid = [r for r in group_results if r["mae"] is not None]
    if not valid:
        print(f"\n{group_name}: no versions with {group['primary_metric']} metric")
        continue

    # Find best (lowest MAE)
    best = min(valid, key=lambda r: r["mae"])
    latest = max(valid, key=lambda r: r["version"])

    print(f"\n{'='*60}")
    print(f"{group_name.upper()} COMPARISON")
    print(f"{'='*60}")
    print(f"  Best:   v{best['version']} — {group['primary_metric']}={best['mae']:.3f} (files={best['n_files']})")
    print(f"  Latest: v{latest['version']} — {group['primary_metric']}={latest['mae']:.3f} (files={latest['n_files']})")

    if best["version"] == latest["version"]:
        print(f"  --> Latest IS the best. More data helped!")
    else:
        diff = latest["mae"] - best["mae"]
        pct = 100 * diff / best["mae"]
        print(f"  --> Latest is {diff:+.3f} ({pct:+.1f}%) vs best. Earlier version with less data was better.")
        print(f"      This can happen with noisy sim data or overfitting to airport distribution.")

    # Promote best version with "champion" alias
    model_name = group["primary"]
    try:
        client.set_registered_model_alias(model_name, "champion", str(best["version"]))
        print(f"  Set alias 'champion' on {model_name} v{best['version']}")
    except Exception as e:
        print(f"  WARNING: Could not set alias: {e}")

    # Also promote coarse model — find matching version (same run produces both)
    coarse_name = group.get("coarse")
    if coarse_name:
        try:
            coarse_versions = client.search_model_versions(f"name='{coarse_name}'")
            # Match by run_id
            matching = [cv for cv in coarse_versions if cv.run_id == best["run_id"]]
            if matching:
                cv = matching[0]
                client.set_registered_model_alias(coarse_name, "champion", cv.version)
                print(f"  Set alias 'champion' on {coarse_name} v{cv.version}")
        except Exception as e:
            print(f"  WARNING: Could not promote coarse model: {e}")

    # Promote board model if exists
    board_name = group.get("board")
    if board_name:
        try:
            board_versions = client.search_model_versions(f"name='{board_name}'")
            matching = [bv for bv in board_versions if bv.run_id == best["run_id"]]
            if matching:
                bv = matching[0]
                client.set_registered_model_alias(board_name, "champion", bv.version)
                print(f"  Set alias 'champion' on {board_name} v{bv.version}")
        except Exception as e:
            print(f"  WARNING: Could not promote board model: {e}")

    promotions[group_name] = {
        "best_version": best["version"],
        "best_mae": best["mae"],
        "latest_version": latest["version"],
        "latest_mae": latest["mae"],
        "more_data_helped": best["version"] == latest["version"],
        "n_versions_compared": len(valid),
    }

# COMMAND ----------

# MAGIC %md
# MAGIC ## Export Champion Pickles to UC Volume
# MAGIC
# MAGIC The app loads models from UC Volume pickles at startup.
# MAGIC Download the champion's MLflow artifacts and save as the active pickles.

# COMMAND ----------

import os, shutil, tempfile

VOLUME_PATH = f"/Volumes/{UC_CATALOG}/{UC_SCHEMA}/simulation_data"
MODEL_DIR = f"{VOLUME_PATH}/ml_models"
os.makedirs(MODEL_DIR, exist_ok=True)

# Map: (group_name, model_key) -> pickle filename in UC Volume
PICKLE_MAP = {
    ("turnaround", "primary"): [
        ("obt_refined_model", "obt_refined.pkl"),
    ],
    ("turnaround", "coarse"): [
        ("obt_coarse_model", "obt_coarse.pkl"),
    ],
    ("turnaround", "board"): [
        ("obt_board_model", "obt_board.pkl"),
    ],
    ("obt_departure", "primary"): [
        ("obt_departure_refined_model", "obt_departure_refined.pkl"),
    ],
    ("obt_departure", "coarse"): [
        ("obt_departure_coarse_model", "obt_departure_coarse.pkl"),
    ],
}

for group_name, group in MODEL_GROUPS.items():
    group_results = results.get(group_name, [])
    if not group_results:
        continue

    valid = [r for r in group_results if r["mae"] is not None]
    if not valid:
        continue

    best = min(valid, key=lambda r: r["mae"])
    best_run_id = best["run_id"]

    # Download artifacts from the champion's MLflow run
    for model_key in ["primary", "coarse", "board"]:
        pkl_entries = PICKLE_MAP.get((group_name, model_key), [])
        if not pkl_entries:
            continue

        model_name = group.get(model_key)
        if not model_name:
            continue

        for artifact_subdir, pkl_filename in pkl_entries:
            try:
                # Download the artifact directory from MLflow
                local_dir = mlflow.artifacts.download_artifacts(
                    run_id=best_run_id,
                    artifact_path=artifact_subdir,
                    dst_path=tempfile.mkdtemp(),
                )
                # Find the pkl file in the downloaded artifacts
                pkl_src = None
                for root, dirs, files in os.walk(local_dir):
                    for f in files:
                        if f.endswith(".pkl"):
                            pkl_src = os.path.join(root, f)
                            break
                    if pkl_src:
                        break

                if pkl_src:
                    dest = os.path.join(MODEL_DIR, pkl_filename)
                    shutil.copy2(pkl_src, dest)
                    size_mb = os.path.getsize(dest) / (1024 * 1024)
                    print(f"  Exported {pkl_filename} ({size_mb:.1f} MB) from run {best_run_id[:8]}...")
                else:
                    print(f"  No .pkl found in {artifact_subdir} artifacts for run {best_run_id[:8]}")
            except Exception as e:
                # The training notebooks also save pickles directly — those are already there
                print(f"  Could not export {pkl_filename} from MLflow: {e}")
                existing = os.path.join(MODEL_DIR, pkl_filename)
                if os.path.exists(existing):
                    print(f"  (existing pickle at {existing} will be used)")

print(f"\nModel pickles in {MODEL_DIR}:")
for f in sorted(os.listdir(MODEL_DIR)):
    size_mb = os.path.getsize(os.path.join(MODEL_DIR, f)) / (1024 * 1024)
    print(f"  {f}: {size_mb:.1f} MB")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary

# COMMAND ----------

print("\n" + "=" * 60)
print("MODEL COMPARISON SUMMARY")
print("=" * 60)

for group_name, p in promotions.items():
    status = "MORE DATA HELPED" if p["more_data_helped"] else "EARLIER VERSION BETTER"
    print(f"\n{group_name}:")
    print(f"  Champion: v{p['best_version']} (MAE={p['best_mae']:.3f})")
    print(f"  Latest:   v{p['latest_version']} (MAE={p['latest_mae']:.3f})")
    print(f"  Versions compared: {p['n_versions_compared']}")
    print(f"  Verdict: {status}")

# COMMAND ----------

dbutils.notebook.exit(json.dumps({
    "status": "PASS",
    "promotions": promotions,
}))
