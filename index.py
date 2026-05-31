import subprocess

try:
    subprocess.run(["bash", "start.sh"], check=True)
except KeyboardInterrupt:
    pass