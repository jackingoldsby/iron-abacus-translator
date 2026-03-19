#!/usr/bin/env python3
"""
API Key Verification Script

Verifies that the OpenAI API key is correctly set and working.
This should be run before executing the batch processing pipeline.
"""

import sys
import os


def main():
    print("=" * 60)
    print("OpenAI API Key Verification")
    print("=" * 60)
    print()

    # Step 1: Check environment variable
    print("Step 1: Checking OPENAI_API_KEY environment variable...")
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        print("  x OPENAI_API_KEY is not set.")
        print()
        print("Set in ~/.zshrc: export OPENAI_API_KEY='...'")
        print("Then run: source ~/.zshrc")
        return 1

    print(f"  OK Key found: {api_key[:20]}...{api_key[-10:]}")
    print(f"  OK Key length: {len(api_key)} characters")
    print()

    # Step 2: Verify API key with test call
    print("Step 2: Verifying API key with test call...")
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        client.models.list()
        print("  OK API key verified successfully!")
        print()
        print("=" * 60)
        print("ALL CHECKS PASSED")
        print("=" * 60)
        print()
        print("You can now run the batch processing pipeline.")
        return 0
    except Exception as e:
        print(f"  x API key verification failed: {e}")
        print()
        print("=" * 60)
        print("VERIFICATION FAILED")
        print("=" * 60)
        print()
        print("Please check that your API key is valid and has correct permissions.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
