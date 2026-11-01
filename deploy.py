#!/usr/bin/env python3
"""ShieldAI Deployment Script"""
import subprocess
import sys
from pathlib import Path

def check_git_status():
    result = subprocess.run(
        ['git', 'status', '--porcelain'],
        capture_output=True,
        text=True
    )
    if result.stdout:
        print("WARNING: Uncommitted changes detected")
        return False
    return True

def run_tests():
    result = subprocess.run(
        ['python', 'src/test_auto.py', '--all'],
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        print("ERROR: Tests failed")
        return False
    print("✓ All tests passed")
    return True

def deploy():
    print("Deploying ShieldAI...")
    subprocess.run(['python', '-m', 'build'], check=True)
    subprocess.run(['python', '-m', 'twine', 'upload', 'dist/*'], check=True)
    print("✓ Deployment successful")

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--test':
        if check_git_status() and run_tests():
            print("✓ Pre-deployment checks passed")
        else:
            print("✗ Pre-deployment checks failed")
            sys.exit(1)
    elif len(sys.argv) > 1 and sys.argv[1] == '--deploy':
        if check_git_status():
            print("Skipping deployment - uncommitted changes detected")
        else:
            if run_tests() and deploy():
                print("✓ Deployed successfully")
            else:
                print("✗ Deployment failed")
                sys.exit(1)
    else:
        print("Usage: python deploy.py [--test|--deploy]")
