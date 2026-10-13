import os
import tempfile
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="scan2book-test-")
os.environ.pop("ANTHROPIC_API_KEY", None)
