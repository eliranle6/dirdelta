"""The copy's name and header, and how often it's uploaded"""


FILE_NAME = 'files.jsonl'
HEADER_KEY = 'dirdeltaFileList'
# How often the Uploader looks whether the list changed since it was last uploaded, in seconds
UPLOAD_INTERVAL = 60
NUM_RETRIES = 3

# What check() did: put Drive's copy in the cache (it was newer), or nothing (the same, or none
# there, or the cache's is newer: the Uploader will upload it)
USED = 'used'
