import React, { useState, useEffect } from 'react';
import { getUser } from '../services/file_auth';
import { getBookmarks, deleteBookmarkedNode, updateBookmarkDescription } from '../services/file_auth';
import BookmarkTable from '../components/BookmarkTable';

// import '../styles/UserProfile.css';

const UserProfile = ({ onBookmarkRefresh }) => {
    const [user, setUser] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    const [bookmarks, setBookmarks] = useState([]);
    const [loadingBookmarks, setLoadingBookmarks] = useState(true);
    const [bookmarksError, setBookmarksError] = useState(null);

    // Function to refresh bookmarks
    const refreshBookmarks = async () => {
        setLoadingBookmarks(true);
        setBookmarksError(null);
        try {
            const result = await getBookmarks();
            const data = Array.isArray(result.data)
                ? result.data.map(item =>
                    typeof item === 'string' ? { node: item } : item
                )
                : [];
            setBookmarks(data);
        } catch (err) {
            setBookmarksError(err.message || 'Failed to load bookmarks');
        } finally {
            setLoadingBookmarks(false);
        }
    };

    useEffect(() => {
        const fetchUser = async () => {
            setUser({ name: "name", email: "email" });
            setLoading(false);
            setError(null);

            try {
                const result = await getUser();
                console.log("Result: ", result);
                setUser(result.data);
            } catch (err) {
                setError(err.message);
            } finally {
                setLoading(false);
            }
        };

        fetchUser();
    }, []);

    useEffect(() => {
        refreshBookmarks();
        
        // Listen for bookmark refresh events
        const handleBookmarkRefresh = () => {
            refreshBookmarks();
        };
        
        window.addEventListener('bookmark-refresh', handleBookmarkRefresh);
        
        return () => {
            window.removeEventListener('bookmark-refresh', handleBookmarkRefresh);
        };
    }, []);

    if (loading) {
        return <div className="userprofile-container">Loading...</div>;
    }

    if (error) {
        console.log("Error: ", error);
        return (
            <div className="userprofile-container">
                <div className="userprofile-container error">{error}</div>
            </div>
        );
    }

    const handleDeleteBookmark = async (node) => {
        try {
            await deleteBookmarkedNode({ node });
            setBookmarks((prev) => prev.filter((b) => b.node !== node));
        } catch (err) {
            console.error('Error deleting bookmark:', err);
            alert('Failed to delete bookmark');
        }
    };

    const handleUpdateDescription = async (node, description) => {
        try {
          await updateBookmarkDescription({ node, description });
          setBookmarks((prev) =>
            prev.map((b) => (b.node === node ? { ...b, description } : b))
          );
        } catch (err) {
          console.error('Failed to update description:', err);
          alert('Error updating description');
        }
    };

    return (
        <div className="userprofile-container">
            <div className="profile-card">
                <h1 className="profile-name">{user.firstname} {user.lastname}</h1>
                <p className="profile-email">{user.email}</p>
            </div>
            <div className="bookmarks-section" style={{ marginTop: '2rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                    <h2>Your Bookmarked Nodes</h2>
                    <button 
                        onClick={refreshBookmarks}
                        style={{
                            padding: '0.5rem 1rem',
                            borderRadius: '0.25rem',
                            border: 'none',
                            backgroundColor: '#007bff',
                            color: 'white',
                            cursor: 'pointer'
                        }}
                    >
                        Refresh
                    </button>
                </div>

                {loadingBookmarks ? (
                    <div>Loading bookmarks…</div>
                ) : bookmarksError ? (
                    <div className="error">{bookmarksError}</div>
                ) : bookmarks.length === 0 ? (
                    <div>No bookmarks yet.</div>
                ) : (
                    <BookmarkTable
                        data={bookmarks}
                        onDelete={handleDeleteBookmark}
                        onUpdateDescription={handleUpdateDescription}/>
                )}
            </div>
        </div>
    );
};

export default UserProfile;
