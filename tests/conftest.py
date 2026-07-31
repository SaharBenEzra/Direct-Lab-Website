import os

# Must be set before `app` is imported anywhere below, since app.py reads
# these into module-level constants at import time.
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ["MONGO_DB_NAME"] = "directlab_test"
os.environ["SAVE_TO_LOCAL_DISK"] = "false"
