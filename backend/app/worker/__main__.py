import uvloop

from app.config import get_settings
from app.worker.consumer import run_worker


def main() -> None:
    uvloop.run(run_worker(get_settings()))


if __name__ == "__main__":
    main()
