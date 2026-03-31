import multiprocessing

bind = "0.0.0.0:8000"
workers = multiprocessing.cpu_count() + 1
worker_class = "gevent"
max_requests = 1000
max_requests_jitter = 50
timeout = 60
accesslog = "-"
errorlog = "-"
loglevel = "info"
graceful_timeout = 30
capture_output = True
proc_name = "eform_data_collection"
