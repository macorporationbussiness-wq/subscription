#!/usr/bin/env python3
"""
Script to delete all movies from the database while preserving:
- User accounts
- Subscriptions
- Payments
- Categories
- Website settings
- Contact info
- Social media
- About us content
"""

import sqlite3

def delete_all_movies():
    try:
        conn = sqlite3.connect('database.db')
        cursor = conn.cursor()
        
        print("Deleting all movies from database...")
        
        # Step 1: Delete all watchlist entries (references to movies)
        print("  - Removing watchlist entries...")
        cursor.execute('DELETE FROM watchlist')
        print(f"    Deleted {cursor.rowcount} watchlist entries")
        
        # Step 2: Delete all watched entries (references to movies)
        print("  - Removing watched history entries...")
        cursor.execute('DELETE FROM watched')
        print(f"    Deleted {cursor.rowcount} watched entries")
        
        # Step 3: Delete all movies
        print("  - Removing movies...")
        cursor.execute('DELETE FROM movies')
        print(f"    Deleted {cursor.rowcount} movies")
        
        # Commit the transaction
        conn.commit()
        
        # Verify the deletion
        cursor.execute('SELECT COUNT(*) FROM movies')
        movie_count = cursor.fetchone()[0]
        cursor.execute('SELECT COUNT(*) FROM users')
        user_count = cursor.fetchone()[0]
        cursor.execute('SELECT COUNT(*) FROM subscriptions')
        sub_count = cursor.fetchone()[0]
        
        print("\n✓ Successfully deleted all movies!")
        print(f"\nDatabase Status:")
        print(f"  - Movies remaining: {movie_count}")
        print(f"  - User accounts: {user_count} (preserved)")
        print(f"  - Subscriptions: {sub_count} (preserved)")
        
        conn.close()
        
    except sqlite3.Error as e:
        print(f"✗ Database error: {e}")
        if conn:
            conn.close()
        return False
    
    return True

if __name__ == '__main__':
    success = delete_all_movies()
    exit(0 if success else 1)
