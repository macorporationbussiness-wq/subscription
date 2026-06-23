CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    role TEXT DEFAULT 'user',
    status TEXT DEFAULT 'active',
    subscription_status TEXT DEFAULT 'inactive'
);

CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS movies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    category_id INTEGER NOT NULL,
    thumbnail TEXT,
    banner_image TEXT,
    description TEXT,
    video_url TEXT,
    trailer_url TEXT,
    cast TEXT,
    screenshots TEXT,
    rating REAL DEFAULT 0.0,
    featured INTEGER DEFAULT 0,
    show_in_banner INTEGER DEFAULT 0,
    FOREIGN KEY (category_id) REFERENCES categories(id)
);

-- Add new columns if they don't exist
ALTER TABLE movies ADD COLUMN trailer_url TEXT;
ALTER TABLE movies ADD COLUMN cast TEXT;
ALTER TABLE movies ADD COLUMN screenshots TEXT;
ALTER TABLE movies ADD COLUMN rating REAL DEFAULT 0.0;
ALTER TABLE movies ADD COLUMN banner_image TEXT;
ALTER TABLE movies ADD COLUMN description TEXT;
ALTER TABLE movies ADD COLUMN show_in_banner INTEGER DEFAULT 0;

CREATE TABLE IF NOT EXISTS watchlist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    movie_id INTEGER NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (movie_id) REFERENCES movies(id),
    UNIQUE(user_id, movie_id)
);

CREATE TABLE IF NOT EXISTS watched (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    movie_id INTEGER NOT NULL,
    watched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (movie_id) REFERENCES movies(id),
    UNIQUE(user_id, movie_id)
);

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    plan TEXT NOT NULL,
    screenshot TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    payment_method TEXT,
    bank_name TEXT,
    account_number TEXT,
    account_holder TEXT,
    amount REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    plan TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    start_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    end_date TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS subscription_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    duration_months INTEGER NOT NULL,
    price_pkr REAL NOT NULL,
    discount_percentage REAL DEFAULT 0,
    features TEXT,
    is_active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Insert sample categories
INSERT OR IGNORE INTO categories (name) VALUES ('Action'), ('Drama'), ('Comedy'), ('Horror'), ('Romance');

-- Insert sample movies
INSERT OR IGNORE INTO movies (title, category_id, thumbnail, video_url, rating) VALUES 
('Action Movie 1', 1, 'static/uploads/thumbnail1.jpg', 'https://example.com/video1.mp4', 8.5),
('Drama Movie 1', 2, 'static/uploads/thumbnail2.jpg', 'https://example.com/video2.mp4', 9.0),
('Comedy Movie 1', 3, 'static/uploads/thumbnail3.jpg', 'https://example.com/video3.mp4', 7.8),
('Horror Movie 1', 4, 'static/uploads/thumbnail4.jpg', 'https://example.com/video4.mp4', 6.5),
('Romance Movie 1', 5, 'static/uploads/thumbnail5.jpg', 'https://example.com/video5.mp4', 8.0);

-- Insert default subscription plans
INSERT OR IGNORE INTO subscription_plans (name, duration_months, price_pkr, discount_percentage, features, is_active) VALUES 
('Basic Monthly', 1, 500, 0, 'HD Streaming, 1 Device, Ad-free', 1),
('Standard Monthly', 1, 800, 0, 'Full HD Streaming, 2 Devices, Ad-free, Download Content', 1),
('Premium Monthly', 1, 1200, 0, '4K Ultra HD, 4 Devices, Ad-free, Download Content, Offline Viewing', 1),
('Basic Yearly', 12, 4500, 25, 'HD Streaming, 1 Device, Ad-free, 3 Months Free', 1),
('Standard Yearly', 12, 7200, 25, 'Full HD Streaming, 2 Devices, Ad-free, Download Content, 3 Months Free', 1),
('Premium Yearly', 12, 10800, 25, '4K Ultra HD, 4 Devices, Ad-free, Download Content, Offline Viewing, 3 Months Free', 1);

-- Website Settings
CREATE TABLE IF NOT EXISTS website_settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_name TEXT DEFAULT 'StreamFlix',
    primary_color TEXT DEFAULT '#e50914',
    secondary_color TEXT DEFAULT '#ff3858',
    logo_url TEXT,
    favicon_url TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Social Media Platforms
CREATE TABLE IF NOT EXISTS social_media (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    url TEXT NOT NULL,
    icon_class TEXT,
    is_active INTEGER DEFAULT 1,
    display_order INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- About Us Content
CREATE TABLE IF NOT EXISTS about_us (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT DEFAULT 'About StreamFlix',
    content TEXT,
    mission TEXT,
    vision TEXT,
    image_url TEXT,
    is_active INTEGER DEFAULT 1,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Contact Information
CREATE TABLE IF NOT EXISTS contact_info (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL, -- 'email', 'phone', 'address', 'social'
    label TEXT NOT NULL,
    value TEXT NOT NULL,
    icon_class TEXT,
    is_active INTEGER DEFAULT 1,
    display_order INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Payment Information
CREATE TABLE IF NOT EXISTS payment_info (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    payment_method TEXT NOT NULL,
    account_title TEXT,
    account_number TEXT,
    bank_name TEXT,
    branch_code TEXT,
    instructions TEXT,
    is_active INTEGER DEFAULT 1,
    display_order INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Insert default website settings
INSERT OR IGNORE INTO website_settings (site_name, primary_color, secondary_color) VALUES 
('StreamFlix', '#e50914', '#ff3858');

-- Insert default social media platforms
INSERT OR IGNORE INTO social_media (platform, url, icon_class, display_order) VALUES 
('Facebook', 'https://facebook.com/streamflix', 'fab fa-facebook-f', 1),
('Twitter', 'https://twitter.com/streamflix', 'fab fa-twitter', 2),
('Instagram', 'https://instagram.com/streamflix', 'fab fa-instagram', 3),
('YouTube', 'https://youtube.com/streamflix', 'fab fa-youtube', 4);

-- Insert default about us content
INSERT OR IGNORE INTO about_us (title, content, mission, vision) VALUES 
('About StreamFlix', 'StreamFlix is your premier destination for streaming movies and TV shows online. We offer a vast library of content with high-quality streaming and an intuitive user interface.', 'To provide the best streaming experience with affordable pricing and excellent customer service.', 'To become the leading streaming platform globally, known for quality content and user satisfaction.', 'static/uploads/about-image.jpg');

-- Insert default contact information
INSERT OR IGNORE INTO contact_info (type, label, value, icon_class, display_order) VALUES 
('email', 'Support Email', 'support@streamflix.com', 'fas fa-envelope', 1),
('phone', 'Customer Support', '+92-300-1234567', 'fas fa-phone', 2),
('address', 'Head Office', '123 Streaming Street, Digital City, Pakistan', 'fas fa-map-marker-alt', 3);

-- Insert default payment information
INSERT OR IGNORE INTO payment_info (payment_method, account_title, account_number, bank_name, instructions, display_order) VALUES 
('JazzCash', 'StreamFlix Services', '03001234567', 'JazzCash', 'Send payment to this JazzCash number and upload screenshot', 1),
('EasyPaisa', 'StreamFlix Services', '03451234567', 'EasyPaisa', 'Send payment to this EasyPaisa number and upload screenshot', 2),
('Bank Transfer', 'StreamFlix Services', '1234567890123', 'HBL Bank', 'Transfer to this account and upload bank receipt', 3);