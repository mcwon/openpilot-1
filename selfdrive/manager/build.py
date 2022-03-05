#!/usr/bin/env python3
import os
import subprocess
import sys
import time
import datetime
import textwrap
from pathlib import Path

# NOTE: Do NOT import anything here that needs be built (e.g. params)
from common.basedir import BASEDIR
from common.spinner import Spinner
from common.text_window import TextWindow
from selfdrive.hardware import TICI
from selfdrive.swaglog import cloudlog, add_file_handler
from selfdrive.version import is_dirty

MAX_CACHE_SIZE = 4e9 if "CI" in os.environ else 2e9
CACHE_DIR = Path("/data/scons_cache" if TICI else "/tmp/scons_cache")

TOTAL_SCONS_NODES = 2405
MAX_BUILD_PROGRESS = 100
PREBUILT = os.path.exists(os.path.join(BASEDIR, 'prebuilt'))


def build(spinner: Spinner, dirty: bool = False) -> None:
  env = os.environ.copy()
  env['SCONS_PROGRESS'] = "1"
  nproc = os.cpu_count()
  j_flag = "" if nproc is None else f"-j{nproc - 1}"

  # for retry in [True, False]:
  scons = subprocess.Popen(["scons", j_flag, "--cache-populate"], cwd=BASEDIR, env=env, stderr=subprocess.PIPE)
  assert scons.stderr is not None

  compile_output = []

  start = time.time()
  # Read progress from stderr and update spinner
  while scons.poll() is None:
    try:
      line = scons.stderr.readline()
      line_ok = scons.stdout.readline()
      if line is None:
        continue
      line = line.rstrip()

      prefix = b'progress: '
      if line.startswith(prefix):
        i = int(line[len(prefix):])
        elapsed = time.time() - start
        elapsed_time = str(datetime.timedelta(seconds=elapsed))
        elapsed_out = elapsed_time[2:7]
        scons_node = str(i) + " / " + str(TOTAL_SCONS_NODES)
        str_out = "Elapsed: " + str(elapsed_out) + "       Nodes: " + str(scons_node) + "       " + str(line_ok)
        spinner.update(str_out)
      elif len(line):
        compile_output.append(line)
        print(line.decode('utf8', 'replace'))
    except Exception:
      pass

  if scons.returncode != 0:
    # Read remaining output
    r = scons.stderr.read().split(b'\n')
    compile_output += r

    # if retry and (not dirty):  # I want to check what errors are immediately.
    #   if not os.getenv("CI"):
    #     print("scons build failed, cleaning in")
    #     for i in range(3, -1, -1):
    #       print("....%d" % i)
    #       time.sleep(1)
    #     subprocess.check_call(["scons", "-c"], cwd=BASEDIR, env=env)
    #   else:
    #     print("scons build failed after retry")
    #     sys.exit(1)
    # else:

    # Build failed log errors
    errors = [line.decode('utf8', 'replace') for line in compile_output
              if any(err in line for err in [b'error: ', b'not found, needed by target'])]
    error_s = "\n".join(errors)
    add_file_handler(cloudlog)
    cloudlog.error("scons build failed\n" + error_s)

    # Show TextWindow
    spinner.close()
    if not os.getenv("CI"):
      error_s = "\n \n".join("\n".join(textwrap.wrap(e, 65)) for e in errors)
      with TextWindow("openpilot failed to build\n \n" + error_s) as t:
        t.wait_for_exit()
    exit(1)
  # else:
  #   break

  # enforce max cache size
  cache_files = [f for f in CACHE_DIR.rglob('*') if f.is_file()]
  cache_files.sort(key=lambda f: f.stat().st_mtime)
  cache_size = sum(f.stat().st_size for f in cache_files)
  for f in cache_files:
    if cache_size < MAX_CACHE_SIZE:
      break
    cache_size -= f.stat().st_size
    f.unlink()


if __name__ == "__main__" and not PREBUILT:
  spinner = Spinner()
  spinner.update("Openpilot starting...")
  build(spinner, is_dirty())
