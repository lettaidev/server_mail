import os
import time
import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from contextlib import contextmanager
from dataclasses import dataclass
import secrets
import string
from flask import Flask, request, jsonify, abort
import mailparser

# Configuration
class Config:
    """Application configuration"""
    DATABASE_PATH = os.environ.get('DATABASE_PATH', 'emails.db')
    SECRET_KEY = os.environ.get('SECRET_KEY', secrets.token_hex(32))
    WEBHOOK_SECRET = os.environ.get('WEBHOOK_SECRET', "LETTAI_SECRET6")
    DEBUG = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    EMAIL_EXPIRY_HOURS = int(os.environ.get('EMAIL_EXPIRY_HOURS', '3'))
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size

# Data models
@dataclass
class EmailMessage:
    """Email message data model"""
    id: str
    subject: str
    text_content: Optional[str]
    html_content: Optional[str]
    from_address: str
    to_address: str
    created_at: int
    expires_at: int

    def to_dict(self, include_content: bool = False) -> Dict:
        """Convert to dictionary for API response"""
        data = {
            'id': self.id,
            'subject': self.subject,
            'createdAt': self.created_at,
            'expiresAt': self.expires_at,
            'fromAddress': self.from_address,
            'toAddress': self.to_address
        }
        
        if include_content:
            data.update({
                'textContent': self.text_content,
                'htmlContent': self.html_content
            })
        
        return data

# Database management
class DatabaseManager:
    """Database operations manager"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Initialize database with optimized schema"""
        with self.get_db_connection() as conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS emails (
                    id TEXT PRIMARY KEY,
                    subject TEXT NOT NULL,
                    text_content TEXT,
                    html_content TEXT,
                    from_address TEXT NOT NULL,
                    to_address TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL
                );
                
                -- Indexes for performance optimization
                CREATE INDEX IF NOT EXISTS idx_to_address ON emails(to_address);
                CREATE INDEX IF NOT EXISTS idx_created_at ON emails(created_at);
                CREATE INDEX IF NOT EXISTS idx_expires_at ON emails(expires_at);
                CREATE INDEX IF NOT EXISTS idx_from_address ON emails(from_address);
                CREATE INDEX IF NOT EXISTS idx_to_created ON emails(to_address, created_at DESC);
            ''')
    
    @contextmanager
    def get_db_connection(self):
        """Context manager for database connections"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    
    def insert_email(self, email: EmailMessage) -> bool:
        """Insert email into database"""
        try:
            with self.get_db_connection() as conn:
                conn.execute('''
                    INSERT INTO emails 
                    (id, subject, text_content, html_content, from_address, to_address, created_at, expires_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    email.id, email.subject, email.text_content, email.html_content,
                    email.from_address, email.to_address, email.created_at, email.expires_at
                ))
                return True
        except sqlite3.IntegrityError:
            logging.warning(f"Email with ID {email.id} already exists")
            return False
        except Exception as e:
            logging.error(f"Error inserting email: {e}")
            raise
    
    def get_emails_by_recipient(self, recipient: str) -> List[EmailMessage]:
        """Get all emails for a specific recipient"""
        with self.get_db_connection() as conn:
            cursor = conn.execute('''
                SELECT id, subject, text_content, html_content, from_address, to_address, created_at, expires_at
                FROM emails 
                WHERE to_address = ? AND expires_at > ?
                ORDER BY created_at DESC
            ''', (recipient, int(time.time())))
            
            return [EmailMessage(**row) for row in cursor.fetchall()]
    
    def get_email_by_id(self, email_id: str) -> Optional[EmailMessage]:
        """Get email by ID"""
        with self.get_db_connection() as conn:
            cursor = conn.execute('''
                SELECT id, subject, text_content, html_content, from_address, to_address, created_at, expires_at
                FROM emails 
                WHERE id = ? AND expires_at > ?
            ''', (email_id, int(time.time())))
            
            row = cursor.fetchone()
            return EmailMessage(**row) if row else None
    
    def delete_email(self, email_id: str) -> bool:
        """Delete email by ID"""
        try:
            with self.get_db_connection() as conn:
                cursor = conn.execute('DELETE FROM emails WHERE id = ?', (email_id,))
                return cursor.rowcount > 0
        except Exception as e:
            logging.error(f"Error deleting email {email_id}: {e}")
            return False
    
    def delete_emails_by_recipient(self, recipient: str) -> int:
        """Delete all emails for a specific recipient"""
        try:
            with self.get_db_connection() as conn:
                cursor = conn.execute('DELETE FROM emails WHERE to_address = ?', (recipient,))
                return cursor.rowcount
        except Exception as e:
            logging.error(f"Error deleting emails for {recipient}: {e}")
            return 0
    
    def cleanup_expired_emails(self):
        """Remove expired emails"""
        with self.get_db_connection() as conn:
            cursor = conn.execute(
                'DELETE FROM emails WHERE expires_at <= ?',
                (int(time.time()),)
            )
            deleted_count = cursor.rowcount
            if deleted_count > 0:
                logging.info(f"Cleaned up {deleted_count} expired emails")

# Email parsing utilities
class EmailParser:
    """Email parsing utilities"""
    
    @staticmethod
    def parse_email_data(raw_data: bytes) -> EmailMessage:
        """Parse email from raw bytes"""
        if not raw_data:
            raise ValueError("Email data is empty")
        
        try:
            mail = mailparser.parse_from_bytes(raw_data)
        except Exception as e:
            raise ValueError(f"Failed to parse email: {e}")
        
        # Validate required fields
        if not mail.from_:
            raise ValueError("Email missing 'from' address")
        if not mail.to:
            raise ValueError("Email missing 'to' address")
        
        # Extract addresses safely
        from_address = EmailParser._extract_email_address(mail.from_)
        to_address = EmailParser._extract_email_address(mail.to)
        
        if not from_address or not to_address:
            raise ValueError("Invalid email addresses")
        
        # Generate unique ID
        # email_id = secrets.token_urlsafe(20)
        email_id = ''.join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(24))
        
        # Calculate timestamps
        current_time = int(time.time())
        expires_at = current_time + (Config.EMAIL_EXPIRY_HOURS * 3600)
        
        return EmailMessage(
            id=email_id,
            subject=mail.subject or "(No Subject)",
            text_content=mail.text_plain[0] if mail.text_plain else None,
            html_content=mail.text_html[0] if mail.text_html else None,
            from_address=from_address,
            to_address=to_address,
            created_at=current_time,
            expires_at=expires_at
        )
    
    @staticmethod
    def _extract_email_address(address_list) -> Optional[str]:
        """Extract email address from address list"""
        if not address_list:
            return None
        
        # Handle different address formats
        if isinstance(address_list[0], (list, tuple)) and len(address_list[0]) >= 2:
            return address_list[0][1]  # (name, email) format
        elif isinstance(address_list[0], str):
            return address_list[0]  # plain email format
        
        return None

# Flask application
def create_app() -> Flask:
    """Application factory"""
    app = Flask(__name__)
    app.config.from_object(Config)
    
    # Initialize database
    db_manager = DatabaseManager(Config.DATABASE_PATH)
    
    # Set up logging
    if not app.debug:
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s %(levelname)s: %(message)s'
        )
    
    # Error handlers
    @app.errorhandler(400)
    def handle_bad_request(e):
        return jsonify({'error': 'Bad request', 'message': 'Invalid request data'}), 400
    
    @app.errorhandler(401)
    def handle_unauthorized(e):
        return jsonify({'error': 'Unauthorized', 'message': 'Authentication required'}), 401
    
    @app.errorhandler(404)
    def handle_not_found(e):
        return jsonify({'error': 'Not found', 'message': 'Resource not found'}), 404
    
    @app.errorhandler(500)
    def handle_internal_error(e):
        logging.error(f"Internal server error: {e}")
        return jsonify({'error': 'Internal server error'}), 500
    
    @app.errorhandler(Exception)
    def handle_general_exception(e):
        logging.error(f"Unhandled exception: {e}")
        return jsonify({'error': 'Internal server error'}), 500
    
    # Routes
    @app.route("/")
    def home():
        """Home page with simple form"""
        return """
            <h1>Chào mừng đến với Email API Service!</h1>
            <div style="margin-top: 20px;">
                <h3>API Endpoints:</h3>
                <ul>
                    <li><strong>POST /webhook</strong> - Nhận email qua webhook (yêu cầu X-Secret header)</li>
                    <li><strong>GET /api/email/{recipient}</strong> - Lấy danh sách email</li>
                    <li><strong>DELETE /api/email/{recipient}</strong> - Xóa tất cả email của recipient</li>
                    <li><strong>GET /api/inbox/{id}</strong> - Lấy chi tiết email</li>
                    <li><strong>DELETE /api/inbox/{id}</strong> - Xóa email theo ID</li>
                    <li><strong>GET /api/health</strong> - Health check</li>
                </ul>
            </div>
        """
    
    @app.route("/webhook", methods=["POST"])
    def webhook():
        """Webhook endpoint for receiving emails"""
        try:
            # Simple secret check
            webhook_secret = Config.WEBHOOK_SECRET
            request_secret = request.headers.get('X-Secret')
            
            if not request_secret or request_secret != webhook_secret:
                return jsonify({'error': 'Unauthorized', 'message': 'Invalid secret'}), 401
            
            # Get email data
            raw_data = request.get_data()
            if not raw_data:
                return jsonify({'error': 'Bad request', 'message': 'No email data provided'}), 400
            
            # Parse email
            email = EmailParser.parse_email_data(raw_data)
            
            # Save to database
            if db_manager.insert_email(email):
                logging.info(f"Email saved successfully: {email.id}")
                return jsonify(email.to_dict(include_content=True)), 201
            else:
                return jsonify({'error': 'Email already exists'}), 409
                
        except ValueError as e:
            logging.warning(f"Email parsing error: {e}")
            return jsonify({'error': 'Bad request', 'message': f'Invalid email format: {e}'}), 400
        except Exception as e:
            logging.error(f"Webhook error: {e}")
            return jsonify({'error': 'Internal server error', 'message': 'Failed to process email'}), 500
    
    @app.route("/api/email/<recipient>", methods=["GET"])
    def get_emails_for_recipient(recipient: str):
        """Get all emails for a specific recipient"""
        try:
            # Basic email validation
            if "@" not in recipient or "." not in recipient:
                return jsonify({'error': 'Bad request', 'message': 'Invalid email address format'}), 400
            
            # Clean up expired emails
            db_manager.cleanup_expired_emails()
            
            # Get emails
            emails = db_manager.get_emails_by_recipient(recipient)
            
            return jsonify([email.to_dict() for email in emails]), 200
            
        except Exception as e:
            logging.error(f"Error getting emails for {recipient}: {e}")
            return jsonify({'error': 'Internal server error', 'message': 'Failed to retrieve emails'}), 500
    
    @app.route("/api/inbox/<email_id>", methods=["GET"])
    def get_email_by_id(email_id: str):
        """Get specific email by ID"""
        try:
            # Clean up expired emails
            db_manager.cleanup_expired_emails()
            
            # Get email
            email = db_manager.get_email_by_id(email_id)
            
            if not email:
                return jsonify({'error': 'Not found', 'message': 'Email not found or expired'}), 404
            
            return jsonify(email.to_dict(include_content=True)), 200
            
        except Exception as e:
            logging.error(f"Error getting email {email_id}: {e}")
            return jsonify({'error': 'Internal server error', 'message': 'Failed to retrieve email'}), 500
    
    @app.route("/api/inbox/<email_id>", methods=["DELETE"])
    def delete_email_by_id(email_id: str):
        """Delete specific email by ID"""
        try:
            # Delete email
            if db_manager.delete_email(email_id):
                logging.info(f"Email deleted successfully: {email_id}")
                return jsonify({'message': 'Email deleted successfully'}), 200
            else:
                return jsonify({'error': 'Not found', 'message': 'Email not found'}), 404
                
        except Exception as e:
            logging.error(f"Error deleting email {email_id}: {e}")
            return jsonify({'error': 'Internal server error', 'message': 'Failed to delete email'}), 500
    
    @app.route("/api/email/<recipient>", methods=["DELETE"])
    def delete_emails_for_recipient(recipient: str):
        """Delete all emails for a specific recipient"""
        try:
            # Basic email validation
            if "@" not in recipient or "." not in recipient:
                return jsonify({'error': 'Bad request', 'message': 'Invalid email address format'}), 400
            
            # Delete emails
            deleted_count = db_manager.delete_emails_by_recipient(recipient)
            
            if deleted_count > 0:
                logging.info(f"Deleted {deleted_count} emails for {recipient}")
                return jsonify({'message': f'Deleted {deleted_count} emails successfully'}), 200
            else:
                return jsonify({'message': 'No emails found to delete'}), 200
                
        except Exception as e:
            logging.error(f"Error deleting emails for {recipient}: {e}")
            return jsonify({'error': 'Internal server error', 'message': 'Failed to delete emails'}), 500
    
    @app.route("/api/health", methods=["GET"])
    def health_check():
        """Health check endpoint"""
        return jsonify({
            'status': 'healthy',
            'timestamp': int(time.time()),
            'version': '1.0.0'
        }), 200
    
    return app

# Application entry point
if __name__ == "__main__":
    app = create_app()
    
    # Run development server
    app.run(
        debug=Config.DEBUG,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000))
    )
