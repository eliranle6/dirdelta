"""Importing photos from a phone (or any dir) into a local replica, in the web version (web/importing.py):
copied into an import of their own (store.py: resumable, since a phone's link may drop; copying.py),
each tagged with where the replica and its synced ones have it already (known.py), grouped by day with
where the replica's photos of that day are (suggest.py), then moved into the dirs chosen (applying.py)"""
