from dagster import Definitions

from dagster_pipeline.assets import ALL_ASSETS
from dagster_pipeline.jobs import ai_service_pipeline_job, ai_service_transcription_job


defs = Definitions(
    assets=ALL_ASSETS,
    jobs=[ai_service_pipeline_job, ai_service_transcription_job],
)

