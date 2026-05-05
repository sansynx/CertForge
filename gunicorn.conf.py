import multiprocessing

# Worker config
workers = 1  # free tier has 0.1 CPU — more workers just compete
worker_class = "sync"
timeout = 120  # NPTEL fetch + PDF processing can take time on cold start
graceful_timeout = 30
keepalive = 5

# Logging
accesslog = "-"
errorlog = "-"
loglevel = "info"
