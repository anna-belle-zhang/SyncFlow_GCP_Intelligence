#!/usr/bin/env python3
"""
Entry point for Cloud Run deployment of SyncFlow GCP Intelligence Backend.
"""

import os
import sys

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from syncflow_server import main

if __name__ == '__main__':
    main()
