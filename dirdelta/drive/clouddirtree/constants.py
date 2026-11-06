"""How a Drive tree's changes are made: how many at once, in what requests, retried how often"""


# How many files are uploaded at once. A few: Drive limits how fast a user makes files (about 2-3 a
# second), so more would only meet its rate limit errors.
UPLOAD_THREADS = 4
# Smaller files are uploaded in one request; bigger ones as resumable uploads (a request to start,
# then the data in chunks), worth it only where a cut-off upload has much to lose
RESUMABLE_MIN_SIZE = 5 * 1024 * 1024
# How many times the client retries a request that failed on a rate limit or a server error, waiting
# longer each time (exponential backoff)
NUM_RETRIES = 5
# How much of a file a download with progress (see fetch_file()) asks Drive for at a time
PROGRESS_CHUNK_SIZE = 4 * 1024 * 1024
# The most requests in a batch request, and ids that generateIds gives at once (the API's limits)
MAX_BATCH_SIZE = 100
MAX_GENERATED_IDS = 1000
# How many folders one files().list asks what's in ("'A' in parents or 'B' in parents ..."), short
# of a query Drive finds too long or complex
MAX_FOLDERS_PER_QUERY = 30
# How many of the folders or files a confirmation's note lists
MAX_LISTED = 5
# What's added to a file's relpath (with its id after it) when the tree already has one there
DUP_SUFFIX = '___DUP__'
