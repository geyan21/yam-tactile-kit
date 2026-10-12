"""The downloadable source must rebuild the site without a prior CAD environment."""

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT=Path(__file__).resolve().parents[2]
# The complete offline packet now approaches 1.9 GB. Shared CI runners
# need more time for compression than the earlier, smaller package.
CLEAN_STEP_TIMEOUT_SECONDS=360
sys.path.insert(0,str(ROOT/"src"))
from tactile_kit.records import execution

spec=importlib.util.spec_from_file_location("engineering_site_builder",ROOT/"engineering/scripts/build_site.py")
builder=importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class CleanSiteTests(unittest.TestCase):
    def test_fresh_source_build_and_downloads(self):
        with execution(ROOT/"build/records","Rebuild the engineering site from a fresh portable source tree with no generated directories") as record:
            record["commands"]=[]
            with tempfile.TemporaryDirectory(prefix="enpire-clean-source-") as temporary:
                clean=Path(temporary)
                for name,data in builder.source_entries().items():
                    path=clean/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
                self.assertFalse((clean/"build").exists())
                for script in ("build_site.py","check_site.py"):
                    command=[sys.executable,str(clean/"engineering/scripts"/script)]
                    process=subprocess.Popen(command,cwd=clean,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                    entry={"command":command,"pid":process.pid};record["commands"].append(entry)
                    started=time.monotonic()
                    while True:
                        try:
                            stdout,stderr=process.communicate(timeout=min(30,max(1,CLEAN_STEP_TIMEOUT_SECONDS-(time.monotonic()-started))))
                            break
                        except subprocess.TimeoutExpired:
                            if time.monotonic()-started<CLEAN_STEP_TIMEOUT_SECONDS:
                                continue
                            record["intentional_stop_requests"].append(f"Stop owned clean-build PID {process.pid}: {CLEAN_STEP_TIMEOUT_SECONDS} second packet-build bound")
                            process.kill();process.communicate()
                            message=f"{script}: clean reproduction exceeded its {CLEAN_STEP_TIMEOUT_SECONDS} second bound"
                            print("::error file=engineering/tests/test_site_clean.py,title=Clean reproduction timeout::"+message,flush=True)
                            self.fail(message)
                    entry["elapsed_s"]=time.monotonic()-started
                    entry.update({"exit_code":process.returncode,"stdout":stdout[-2000:],"stderr":stderr[-4000:]})
                    self.assertEqual(process.returncode,0,f"{script} failed from a clean tree:\n{stderr[-4000:]}")
                self.assertTrue((clean/"build/site/index.html").is_file())
                self.assertTrue((clean/"build/site/downloads/enpire-engineering-kit.zip").is_file())
                self.assertFalse((clean/"build/engineering/tools/cad-venv").exists())


if __name__=="__main__":
    unittest.main()
