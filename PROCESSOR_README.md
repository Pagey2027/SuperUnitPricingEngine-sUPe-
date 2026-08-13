# Small shim to prefer creating Processor via bnp_processor.make_and_configure_processor
# This file intentionally minimal to preserve backwards compatibility for callers
# that import configure_processing/process_day from bnp_helpers_processing.
#
# After adopting this wrapper, consumers can either:
# - continue calling bnp_helpers_processing.configure_processing(...) (no change), or
# - construct and use a Processor via bnp_processor.Processor/ make_and_configure_processor.
