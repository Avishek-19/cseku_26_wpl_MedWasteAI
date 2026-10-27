"""One public proxy, one API process, Next.js and the existing workflow worker."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def main():
    env = os.environ.copy()
    hostname = env.get("RENDER_EXTERNAL_HOSTNAME", "").strip()
    if not hostname:
        raise SystemExit("RENDER_EXTERNAL_HOSTNAME must be the public hostname")
    base = "https://" + hostname
    env.setdefault("ENVIRONMENT", "production")
    env.setdefault("DEBUG", "false")
    env.setdefault("AUTH_COOKIE_SECURE", "true")
    env.setdefault("FRONTEND_PUBLIC_BASE_URL", base)
    env.setdefault("PAYMENT_PUBLIC_BASE_URL", base)
    env.setdefault("CORS_ORIGINS", env["FRONTEND_PUBLIC_BASE_URL"])
    env.setdefault("TRUSTED_HOSTS", hostname + ",localhost,127.0.0.1")
    env.setdefault("LOCAL_AI_ENABLED", "false")
    env.setdefault("PAYMENT_MODE", "disabled")
    env.setdefault("TRACKING_MODE", "real")
    env.setdefault("TRACKING_WORKER_COUNT", "1")
    env.setdefault("DATABASE_POOL_SIZE", "2")
    env.setdefault("DATABASE_MAX_OVERFLOW", "2")
    url = env.get("DATABASE_URL", "")
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            url = "postgresql+psycopg2://" + url[len(prefix):]
            break
    if not url.startswith("postgresql+psycopg2://"):
        raise SystemExit("Set DATABASE_URL to the Neon PostgreSQL connection URL")
    env["DATABASE_URL"] = url
    port = int(env.get("PORT", "10000"))
    if not 1 <= port <= 65535:
        raise SystemExit("Invalid PORT")
    Path("/tmp/nginx.conf").write_text('''
worker_processes 1;
pid /tmp/nginx.pid;
error_log /dev/stderr warn;
events { worker_connections 512; }
http {
  include /etc/nginx/mime.types;
  access_log /dev/stdout;
  map $http_upgrade $connection_upgrade { default upgrade; '' close; }
  server {
    listen PORT_VALUE;
    client_max_body_size 11m;
    location /api/v1/ {
      proxy_pass http://127.0.0.1:8000;
      proxy_http_version 1.1;
      proxy_set_header Host $host;
      proxy_set_header X-Forwarded-Proto https;
      proxy_set_header X-Forwarded-For $remote_addr;
      proxy_set_header Upgrade $http_upgrade;
      proxy_set_header Connection $connection_upgrade;
      proxy_read_timeout 90s;
      proxy_buffering off;
    }
    location / {
      proxy_pass http://127.0.0.1:3000;
      proxy_http_version 1.1;
      proxy_set_header Host $host;
      proxy_set_header X-Forwarded-Proto https;
      proxy_set_header X-Forwarded-For $remote_addr;
      proxy_set_header Upgrade $http_upgrade;
      proxy_set_header Connection $connection_upgrade;
    }
  }
}
'''.replace("PORT_VALUE", str(port)))
    # Free Render services have no pre-deploy command: migrate before serving.
    subprocess.run(["alembic", "upgrade", "head"], cwd="/app/backend", env=env, check=True)
    processes = []
    stopping = False

    def stop(_sig, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        processes.append(subprocess.Popen(["uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "127.0.0.1"], cwd="/app/backend", env=env))
        processes.append(subprocess.Popen(["node", "server.js"], cwd="/app/web", env={**env, "PORT": "3000", "HOSTNAME": "127.0.0.1", "NODE_OPTIONS": "--max-old-space-size=192"}))
        # Default on: pending jobs and reconciliation stop while the free server sleeps.
        if env.get("WORKFLOW_WORKER_ENABLED", "true").lower() == "true":
            processes.append(subprocess.Popen(["python", "scripts/run_workflow_worker.py", "--interval", env.get("WORKFLOW_INTERVAL", "60")], cwd="/app/backend", env=env))
        processes.append(subprocess.Popen(["nginx", "-c", "/tmp/nginx.conf", "-g", "daemon off;"], env=env))
        while not stopping:
            if any(p.poll() is not None for p in processes):
                print("A service process exited; restarting the container is required", file=sys.stderr)
                return 1
            time.sleep(0.5)
        return 0
    finally:
        for proc in processes:
            if proc.poll() is None:
                proc.terminate()
        deadline = time.monotonic() + 10
        for proc in processes:
            try:
                proc.wait(timeout=max(0.01, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


if __name__ == "__main__":
    sys.exit(main())
