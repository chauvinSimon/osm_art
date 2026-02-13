import logging
import logging.config

from utils.utils import get_timestamp, ignored_dir, load_logging_config


def setup_logging():
    try:
        logging_config = load_logging_config()

        log_file_dir = ignored_dir / logging_config["log_file_dir"]
        log_file_dir.mkdir(parents=True, exist_ok=True)

        timestamp = get_timestamp()
        log_file_name = logging_config["log_name_template"].format(timestamp=timestamp)
        log_file_path = log_file_dir / log_file_name

        for handler in logging_config["handlers"].values():
            if handler["class"] == "logging.FileHandler":
                handler["filename"] = log_file_path

        logging.config.dictConfig(logging_config)

    except Exception as e:
        logging.error(f"Error loading configuration file: {e}")
        logging.basicConfig(level=logging.INFO)


setup_logging()
logger = logging.getLogger("wood_engraving")
logger.info("logger initialized")
