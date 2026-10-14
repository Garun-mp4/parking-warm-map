"""Download public CNRPark sources with verified HTTP ranges and resumable parts."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import math
import time
import requests

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "source-cache"
BASE = "https://github.com/fabiocarrara/deep-parking/releases/download/archive/"


def small(name: str) -> Path:
    target = CACHE / name
    if target.exists():
        return target
    with requests.get(BASE + name, stream=True, timeout=60) as response:
        response.raise_for_status()
        with target.with_suffix(target.suffix + ".part").open("wb") as output:
            for chunk in response.iter_content(1024 * 1024):
                output.write(chunk)
    target.with_suffix(target.suffix + ".part").replace(target)
    print(name, target.stat().st_size, flush=True)
    return target


def archive() -> Path:
    name = "CNR-EXT_FULL_IMAGE_1000x750.tar"
    target = CACHE / name
    total = 1104364544
    if target.exists() and target.stat().st_size == total:
        return target
    parts = CACHE / "parts"
    parts.mkdir(exist_ok=True)
    block = 16 * 1024 * 1024

    def fetch(index: int) -> Path:
        start, end = index * block, min((index + 1) * block, total) - 1
        part = parts / f"{index:04d}.bin"
        expected = end - start + 1
        if part.exists() and part.stat().st_size == expected:
            return part
        for attempt in range(3):
            try:
                with requests.get(
                    BASE + name + f"?part={index}",
                    headers={"Range": f"bytes={start}-{end}"},
                    stream=True,
                    timeout=60,
                ) as response:
                    response.raise_for_status()
                    if (
                        response.status_code != 206
                        or response.headers.get("Content-Range")
                        != f"bytes {start}-{end}/{total}"
                    ):
                        raise ValueError("Server did not honor requested byte range")
                    with part.with_suffix(".part").open("wb") as output:
                        for chunk in response.iter_content(1024 * 1024):
                            output.write(chunk)
                if part.with_suffix(".part").stat().st_size != expected:
                    raise ValueError("Incomplete source part")
                part.with_suffix(".part").replace(part)
                return part
            except (requests.RequestException, ValueError):
                if attempt == 2:
                    raise
                time.sleep(attempt + 1)
        raise RuntimeError("Unreachable")

    count = math.ceil(total / block)
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(fetch, i) for i in range(count)]
        for done, future in enumerate(as_completed(futures), 1):
            future.result()
            if done % 4 == 0 or done == count:
                print(f"Archive: {done}/{count} verified parts", flush=True)
    with target.open("wb") as output:
        for i in range(count):
            with (parts / f"{i:04d}.bin").open("rb") as source:
                while chunk := source.read(1024 * 1024):
                    output.write(chunk)
    return target


if __name__ == "__main__":
    CACHE.mkdir(parents=True, exist_ok=True)
    small("CNRPark+EXT.csv")
    small("CNRPark+EXT_Trained_Models_mAlexNet.zip")
    archive()
