# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "orjson>=3.13.0",
# ]
# ///
import sys

version = sys.version_info
if version.major < 3 or (version.major == 3 and version.minor < 14):
    raise RuntimeError("This script requires Python 3.14 or higher")

import contextlib
import datetime as dt
import logging
import os
import pprint
import time
from collections.abc import Generator, Iterable, Iterator
from pathlib import Path
from typing import Any, BinaryIO

from compression import zstd

try:
    import orjson as json

    _orjson = True
except ImportError:
    _orjson = False
    import json

logger = logging.getLogger(__name__)


@contextlib.contextmanager
def _setup_logger(level: int = logging.DEBUG) -> Generator[None]:
    logger.setLevel(level)
    now = dt.datetime.now(dt.UTC).strftime("%Y%m%d_%H%M%SZ")
    logs = Path(__file__).parent / "logs"
    logs.mkdir(exist_ok=True)
    with (logs / f"{now}.log").open("w", encoding="utf8") as fp:
        logger.addHandler(logging.StreamHandler(sys.stdout))
        logger.addHandler(logging.StreamHandler(fp))
        yield


def _decode_bin_stream(fp: Iterable[bytes]) -> Iterator[dict[str, Any]]:
    for idx, line in enumerate(fp):
        line = line.decode("utf-8", errors="replace")
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            logger.exception("Error parsing line #%s: %s", idx, line)


def _decode_zlib_bin_stream(fp: BinaryIO) -> Iterator[dict[str, Any]]:
    with zstd.ZstdFile(
        fp,
        options={
            zstd.DecompressionParameter.window_log_max: 31
        },  # 2GB of memory max per chunk
    ) as z_fp:
        yield from _decode_bin_stream(z_fp)


class FileProgressLog:
    file: BinaryIO
    file_size: int
    i: int
    start_time: float
    print_every: int
    max_line_length: int

    def __init__(self, path: os.PathLike[str] | str, file: BinaryIO) -> None:
        self.file = file
        self.file_size = os.path.getsize(path)
        self.i = 0
        self.start_time = time.time()
        self.print_every = 10_000
        self.max_line_length = 0

    def on_row(self) -> None:
        self.i += 1
        if self.i % self.print_every == 0 and self.i > 0:
            self.log_progress()

    def log_progress(self, end: str = "") -> None:
        elapsed = time.time() - self.start_time
        progress = self.file.tell() / self.file_size if not self.file.closed else 1
        remaining = (elapsed / progress - elapsed) if progress > 0 else 0
        time_per_row = elapsed / self.i
        msg = f"{self.i:,} - {progress:.2%} - elapsed: %s - remaining: %s - %s/row" % (
            self._format_time(elapsed),
            self._format_time(remaining),
            self._format_time(time_per_row),
        )
        self.max_line_length = max(self.max_line_length, len(msg))
        logger.debug(msg.ljust(self.max_line_length))

        if time_per_row < 20 / 1000 / 1000:
            self.print_every = 20_000
        elif time_per_row < 50 / 1000 / 1000:
            self.print_every = 10_000
        else:
            self.print_every = 5_000

    @staticmethod
    def _format_time(seconds: float) -> str:
        if seconds == 0:
            return "0s"
        if seconds < 0.001:
            return f"{seconds * 1_000_000:.1f}µs"
        if seconds < 1:
            return f"{seconds * 1_000:.2f}ms"
        elapsedHr = int(seconds // 3600)
        elapsedMin = int((seconds % 3600) // 60)
        elapsedSec = int(seconds % 60)
        return f"{elapsedHr:02}:{elapsedMin:02}:{elapsedSec:02}"


def _read_rows_from_file(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("rb") as fp:
        match path.suffix:
            case ".json":
                json_stream = _decode_bin_stream([fp.read()])
            case ".jsonl" | ".ndjson":
                json_stream = _decode_bin_stream(fp)
            case ".zst":
                json_stream = _decode_zlib_bin_stream(fp)
            case _:
                logger.error("Skipping unknown file extension '%s'", path.name)
                return

        progressLog = FileProgressLog(path, fp)
        for row in json_stream:
            progressLog.on_row()
            yield row

        progressLog.log_progress("\n")


def _iter_files(path: Path, *, recurse: bool):
    if path.is_file():
        yield path
        return

    glob = path.rglob if recurse else path.glob
    for inner_path in glob("*"):
        if inner_path.is_file():
            yield inner_path


def process_row(row: dict[str, Any]) -> None:
    # PUT YOUR CODE HERE

    # example fields
    author = row["author"]
    subreddit = row["subreddit"]
    id = row["id"]
    created = row["created_utc"]
    score = row["score"]
    pprint.pprint(row, sort_dicts=True)
    input()
    # posts only
    # title = row["title"]
    # body = row["selftext"]
    # url = row["url"]
    # comments only
    # body = row["body"]
    # parent = row["parent_id"]	# id/name of the parent comment or post (e.g. t3_abc123 or t1_abc123)
    # link_id = row["link_id"]	# id/name of the post (e.g. t3_abc123)


def main() -> None:
    path = Path(sys.argv[1])
    if not _orjson:
        logger.warning("Recommended to install 'orjson' for faster JSON parsing")

    for idx, file in enumerate(_iter_files(path, recurse=False), 1):
        logger.info(f"Processing file #{idx: 3}: '%s'", file)
        for row in _read_rows_from_file(file):
            process_row(row)

    logger.info("Done :>")


if __name__ == "__main__":
    with _setup_logger():
        main()
