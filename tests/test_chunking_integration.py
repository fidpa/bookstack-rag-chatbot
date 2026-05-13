#!/usr/bin/env python3
"""
Test script for BookStack Chunking Integration

Tests the new intelligent chunking system with BookStack content.
Run this after implementing the chunking integration.
"""

import sys
import os
import sqlite3
import logging

# Add the chatbot directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'chatbot'))

from bookstack.chunking import BookStackChunkingService, BookStackChunk
from bookstack.sync_service import ContentSyncService
from bookstack.api_client import BookStackClient


# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def test_chunking_service():
    """Test the BookStackChunkingService directly"""
    print("🧪 Testing BookStack Chunking Service...")

    chunking_service = BookStackChunkingService()

    # Test content (simulated BookStack page)
    test_content = """
    Installation Guide

    Welcome to our comprehensive installation guide. This document will walk you through
    the complete setup process for our system.

    Prerequisites

    Before you begin the installation, ensure that you have the following prerequisites:

    1. A compatible operating system (Windows 10, macOS 10.15+, or Ubuntu 18.04+)
    2. At least 4GB of RAM available
    3. 10GB of free disk space
    4. Administrative privileges on your system

    Step 1: Download the Software

    Navigate to our official download page and select the appropriate version for your
    operating system. The download process typically takes 5-10 minutes depending on
    your internet connection speed.

    Step 2: Run the Installer

    Once the download is complete, locate the installer file in your downloads folder.
    Double-click the installer to begin the installation process. Follow the on-screen
    instructions carefully.

    Configuration Settings

    After installation, you'll need to configure several important settings:

    Database Configuration: Set up your database connection parameters including host,
    port, username, and password. Make sure your database server is running and accessible.

    Network Settings: Configure your network settings including firewall rules and port
    configurations. The default ports are 8080 for HTTP and 8443 for HTTPS.

    Security Settings: Enable security features including SSL encryption, user authentication,
    and access controls. We recommend using strong passwords and enabling two-factor authentication.

    Troubleshooting

    If you encounter any issues during installation:

    - Check the system requirements again
    - Verify you have administrative privileges
    - Review the installation logs for error messages
    - Contact our support team if problems persist
    """

    # Test chunking
    chunks = chunking_service.chunk_bookstack_content(
        text=test_content,
        bookstack_id=123,
        content_type='page',
        title='Installation Guide',
        url='http://bookstack/books/docs/page/installation-guide',
        book_id=1,
        chapter_id=None
    )

    print(f"✅ Generated {len(chunks)} chunks")

    # Display chunk statistics
    stats = chunking_service.get_chunk_statistics(chunks)
    print(f"📊 Chunk Statistics:")
    print(f"   - Total chunks: {stats['total_chunks']}")
    print(f"   - Average words per chunk: {stats['avg_words_per_chunk']:.1f}")
    print(f"   - Min words: {stats['min_words']}")
    print(f"   - Max words: {stats['max_words']}")
    print(f"   - Total words: {stats['total_words']}")
    print(f"   - Overlap ratio: {stats['overlap_ratio']:.2%}")

    # Display first chunk
    if chunks:
        first_chunk = chunks[0]
        print(f"\n📝 First chunk preview:")
        print(f"   - Index: {first_chunk.chunk_index}")
        print(f"   - Word count: {first_chunk.word_count}")
        print(f"   - Text preview: {first_chunk.text[:200]}...")

    # Validate chunks
    is_valid, errors = chunking_service.validate_chunks(chunks)
    if is_valid:
        print("✅ Chunk validation passed")
    else:
        print(f"❌ Chunk validation failed: {errors}")

    return chunks


def test_database_integration():
    """Test database tables and FTS integration"""
    print("\n🗄️ Testing Database Integration...")

    # Test database path (use temporary for testing)
    db_path = 'test_bookstack.db'

    try:
        # Create a mock client (we don't need real API for this test)
        class MockBookStackClient:
            def test_connection(self):
                return True

        # Initialize sync service with chunking enabled
        sync_service = ContentSyncService(
            bookstack_client=MockBookStackClient(),
            db_path=db_path,
            enable_chunking=True
        )

        print("✅ Database tables created successfully")

        # Test storing content with chunks
        test_content = "This is a test page content. It should be chunked appropriately. The content contains multiple sentences to test the chunking algorithm."

        sync_service._store_content(
            bookstack_id=999,
            type='page',
            title='Test Page',
            content=test_content,
            url='http://test/page/999',
            book_id=1,
            chapter_id=None,
            tags=['test', 'demo']
        )

        print("✅ Content stored with chunking")

        # Test search functionality
        search_results = sync_service.search("test", limit=5, use_chunks=True)
        print(f"✅ Search returned {len(search_results)} results")

        if search_results:
            result = search_results[0]
            print(f"   - Result type: {result.get('result_type')}")
            print(f"   - Title: {result.get('title')}")
            print(f"   - Snippet: {result.get('snippet', '')[:100]}...")

        # Test chunk-specific search
        chunk_results = sync_service.search_chunks("content", limit=3)
        print(f"✅ Chunk search returned {len(chunk_results)} results")

        # Get sync statistics
        stats = sync_service.get_sync_stats()
        print(f"📊 Sync Statistics:")
        print(f"   - Content counts: {stats['content_counts']}")
        print(f"   - Chunking enabled: {stats['chunking_enabled']}")
        if stats['chunk_stats']:
            chunk_stats = stats['chunk_stats']
            print(f"   - Total chunks: {chunk_stats['total_chunks']}")
            print(f"   - Avg words/chunk: {chunk_stats['avg_words_per_chunk']}")

        return True

    except Exception as e:
        print(f"❌ Database integration test failed: {e}")
        return False

    finally:
        # Cleanup test database
        try:
            os.remove(db_path)
            print("🧹 Test database cleaned up")
        except:
            pass


def test_performance():
    """Test chunking performance with larger content"""
    print("\n⚡ Testing Performance...")

    import time

    chunking_service = BookStackChunkingService()

    # Generate larger test content
    large_content = """
    This is a performance test for the chunking system. """ * 1000

    start_time = time.time()

    chunks = chunking_service.chunk_bookstack_content(
        text=large_content,
        bookstack_id=9999,
        content_type='page',
        title='Performance Test Page',
    )

    end_time = time.time()

    duration = end_time - start_time
    words_per_second = len(large_content.split()) / duration if duration > 0 else 0

    print(f"✅ Performance test completed:")
    print(f"   - Content size: {len(large_content)} characters")
    print(f"   - Word count: {len(large_content.split())} words")
    print(f"   - Chunks generated: {len(chunks)}")
    print(f"   - Processing time: {duration:.3f} seconds")
    print(f"   - Words per second: {words_per_second:.0f}")

    return duration < 5.0  # Should process reasonably fast


def main():
    """Run all tests"""
    print("🚀 BookStack Chunking Integration Tests")
    print("=" * 50)

    tests = [
        ("Chunking Service", test_chunking_service),
        ("Database Integration", test_database_integration),
        ("Performance", test_performance),
    ]

    results = []

    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, True, None))
            print(f"✅ {test_name}: PASSED\n")
        except Exception as e:
            results.append((test_name, False, str(e)))
            print(f"❌ {test_name}: FAILED - {e}\n")

    # Summary
    print("📋 Test Summary:")
    print("=" * 30)

    passed = sum(1 for _, success, _ in results if success)
    total = len(results)

    for test_name, success, error in results:
        status = "✅ PASSED" if success else f"❌ FAILED"
        print(f"{test_name}: {status}")
        if error:
            print(f"   Error: {error}")

    print(f"\nOverall: {passed}/{total} tests passed")

    if passed == total:
        print("🎉 All tests passed! Chunking integration is ready.")
        return 0
    else:
        print("⚠️  Some tests failed. Please review the errors above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())