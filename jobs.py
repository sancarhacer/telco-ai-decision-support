import logging

from anomaly_detector import run as run_anomaly_detector
from mock_data_generator import generate_mock_data_tick

log = logging.getLogger(__name__)


def job_generate_mock_data() -> None:
    inserted = generate_mock_data_tick()
    log.info("Mock data tick finished. Inserted network metrics: %s", inserted)


def job_run_anomaly_detection() -> None:
    run_anomaly_detector(mode="incremental", hours=1)
    log.info("Anomaly detection tick finished.")
