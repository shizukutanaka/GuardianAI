#!/usr/bin/env python3
"""ShieldAI Deployment Script"""
import subprocess
import sys

def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        result = subprocess.run(["python", "src/test_auto.py", "--all"], capture_output=True, text=True)
        if result.returncode == 0:
            print("✓ Pre-deployment tests passed")
        else:
            print("✗ Pre-deployment tests failed")
            sys.exit(1)
    elif len(sys.argv) > 1 and sys.argv[1] == "--deploy":
        print("Deploying ShieldAI...")
        result = subprocess.run(["python", "-m", "build"], capture_output=True, text=True)
        if result.returncode == 0:
            result = subprocess.run(["python", "-m", "twine", "upload", "dist/*"], capture_output=True, text=True)
            if result.returncode == 0:
                print("✓ Deployment successful")
            else:
                print("✗ Upload failed:", result.stderr)
                sys.exit(1)
        else:
            print("✗ Build failed:", result.stderr)
            sys.exit(1)
    else:
        print("Usage: python deploy.py [--test|--deploy]")

if __name__ == "__main__":
    main()
