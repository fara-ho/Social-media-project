# Routes for handling requests
import datetime
from flask import Blueprint, request, jsonify, render_template
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy import distinct
from sqlalchemy.exc import IntegrityError
from models import db, User, Post, Comment, Like, Follower
from forms import validate_email, validate_password
from flask_bcrypt import Bcrypt

bcrypt = Bcrypt()

# Create blueprints for different route categories
main_bp = Blueprint('main', __name__)
auth_bp = Blueprint('auth', __name__)
posts_bp = Blueprint('posts', __name__)
users_bp = Blueprint('users', __name__)


@main_bp.route('/', methods=['GET'])
def welcome():
    """Welcome page for the API"""
    return render_template('index.html')


# Show register page
@auth_bp.route('/register', methods=['GET'], endpoint='show_register')
def show_register_form():
    return render_template('register.html')


# Authentication Endpoints
@auth_bp.route('/register', methods=['POST'], endpoint='handle_register')
def handle_register():
    """User Registration Endpoint"""
    if request.content_type != 'application/json':
        return jsonify({"error": "Content-Type must be application/json"}), 400

    data = request.get_json()
    
    # Validate input
    if not all(key in data for key in ['username', 'name', 'email', 'password']):
        return jsonify({"error": "Missing required fields"}), 400
    
    # Validate email
    if not validate_email(data['email']):
        return jsonify({"error": "Invalid email format"}), 400
    
    # Validate password
    if not validate_password(data['password']):
        return jsonify({"error": "Password does not meet requirements"}), 400
    
    # Hash password
    hashed_password = bcrypt.generate_password_hash(data['password']).decode('utf-8')
    
    # Create new user
    new_user = User(
        username=data['username'],
        name=data['name'],
        email=data['email'],
        password_hash=hashed_password
    )
    
    try:
        db.session.add(new_user)
        db.session.commit()
        return jsonify({"message": "User registered successfully", "user_id": new_user.user_id}), 201
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "Username or email already exists"}), 409

# Show login page
@auth_bp.route('/login', methods=['GET'], endpoint='show_login')
def show_login_form():
    return render_template('login.html')


@auth_bp.route('/login', methods=['POST'], endpoint='handle_login')
def handle_login():
    """User Login Endpoint"""
    if request.content_type != 'application/json':
        return jsonify({"error": "Content-Type must be application/json"}), 400

    data = request.get_json()
    
    # Check for required fields
    if not all(key in data for key in ['username', 'password']):
        return jsonify({"error": "Missing username or password"}), 400
    
    # Find user
    user = User.query.filter_by(username=data['username']).first()
    
    # Verify password
    if user and bcrypt.check_password_hash(user.password_hash, data['password']):
        # Create access token
        from flask_jwt_extended import create_access_token
        access_token = create_access_token(identity=str(user.user_id))
        return jsonify({
            "access_token": access_token,
            "user_id": user.user_id,
            "username": user.username
        }), 200
    
    return jsonify({"error": "Invalid credentials"}), 401


    
@posts_bp.route('/create', methods=['GET'])
def create_post_page():
    return render_template('create_post.html')

@posts_bp.route('/api/create', methods=['POST'])
@jwt_required()
def create_post():
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        
        content = data.get('content')
        if not content:
            return jsonify({"error": "Post content is required"}), 400
        
        # Create new post
        new_post = Post(
            user_id=user_id,
            content=content,
            created_at=datetime.datetime.utcnow()
        )
        
        db.session.add(new_post)
        db.session.commit()
        
        return jsonify({
            "message": "Post created successfully",
            "post_id": new_post.post_id
        }), 201
        
    except Exception as e:
        print(f"Error creating post: {str(e)}")
        return jsonify({"error": "Failed to create post"}), 500
    
@posts_bp.route('/discover', methods=['GET'])
def discover_posts_page():
    return render_template('discover_posts.html')

@posts_bp.route('/api/discover', methods=['GET'])
@jwt_required()
def get_discover_posts():
    try:
        user_id = get_jwt_identity()
        
        # Get filter parameters
        date_from = request.args.get('date_from')
        date_to = request.args.get('date_to')
        min_likes = request.args.get('min_likes')
        author_username = request.args.get('author')
        
        # Base query with joins
        query = db.session.query(Post, User, 
                                 db.func.count(distinct(Like.like_id)).label('likes_count'),
                                 db.func.count(distinct(Comment.comment_id)).label('comments_count'))\
            .join(User, User.user_id == Post.user_id)\
            .outerjoin(Like, Like.post_id == Post.post_id)\
            .outerjoin(Comment, Comment.post_id == Post.post_id)\
            .group_by(Post.post_id, User.user_id)
            
        # Apply filters if provided
        if date_from:
            try:
                # Parse date and set time to start of day (00:00:00)
                from_date = datetime.datetime.fromisoformat(date_from)
                from_date = from_date.replace(hour=0, minute=0, second=0, microsecond=0)
                query = query.filter(Post.created_at >= from_date)
            except ValueError:
                pass
                
        if date_to:
            try:
                # Parse date and set time to end of day (23:59:59)
                to_date = datetime.datetime.fromisoformat(date_to)
                to_date = to_date.replace(hour=23, minute=59, second=59, microsecond=999999)
                query = query.filter(Post.created_at <= to_date)
            except ValueError:
                pass
                
        if min_likes and min_likes.isdigit():
            query = query.having(db.func.count(distinct(Like.like_id)) >= int(min_likes))
            
        if author_username:
            query = query.filter(User.username.ilike(f'%{author_username}%'))
            
        # Execute query and order by recency
        results = query.order_by(Post.created_at.desc()).limit(20).all()
        
        posts_data = []
        for post, author, likes_count, comments_count in results:
            # Check if current user liked this post
            user_liked = Like.query.filter_by(
                post_id=post.post_id, 
                user_id=user_id
            ).first() is not None
            
            # Get comments for this post
            comments = Comment.query.filter_by(post_id=post.post_id)\
                .order_by(Comment.created_at.asc()).all()
            
            comments_data = []
            for comment in comments:
                comment_author = User.query.get(comment.user_id)
                comments_data.append({
                    "comment_id": comment.comment_id,
                    "content": comment.content,
                    "created_at": comment.created_at.isoformat(),
                    "author": {
                        "user_id": comment_author.user_id,
                        "username": comment_author.username,
                        "name": comment_author.name
                    }
                })
            
            posts_data.append({
                "post_id": post.post_id,
                "content": post.content,
                "created_at": post.created_at.isoformat(),
                "likes_count": likes_count,
                "comments_count": comments_count,
                "user_liked": user_liked,
                "comments": comments_data,
                "author": {
                    "user_id": author.user_id,
                    "username": author.username,
                    "name": author.name
                }
            })
        
        return jsonify({"posts": posts_data}), 200
        
    except Exception as e:
        print(f"Error discovering posts: {str(e)}")
        return jsonify({"error": "Failed to fetch posts"}), 500
    
@posts_bp.route('/<int:post_id>/like', methods=['POST'])
@jwt_required()
def toggle_like(post_id):
    try:
        user_id = get_jwt_identity()
        
        # Check if post exists
        post = Post.query.get(post_id)
        if not post:
            return jsonify({"error": "Post not found"}), 404
        
        # Check if user already liked the post
        existing_like = Like.query.filter_by(
            post_id=post_id, 
            user_id=user_id
        ).first()
        
        if existing_like:
            # Unlike the post
            db.session.delete(existing_like)
            db.session.commit()
            return jsonify({"message": "Post unliked successfully", "liked": False}), 200
        else:
            # Like the post
            new_like = Like(post_id=post_id, user_id=user_id)
            db.session.add(new_like)
            db.session.commit()
            return jsonify({"message": "Post liked successfully", "liked": True}), 201
            
    except Exception as e:
        db.session.rollback()
        print(f"Error toggling like: {str(e)}")
        return jsonify({"error": "Failed to process like"}), 500

@posts_bp.route('/api/engagement-by-date', methods=['GET'])
@jwt_required()
def get_engagement_by_date():
    try:
        user_id = get_jwt_identity()
        
        # Get data grouped by day
        engagement_data = db.session.query(
            db.func.date(Post.created_at).label('date'),
            db.func.count(distinct(Post.post_id)).label('posts_count'),
            db.func.count(distinct(Like.like_id)).label('likes_count'),
            db.func.count(distinct(Comment.comment_id)).label('comments_count')
        ).outerjoin(Like, Like.post_id == Post.post_id)\
         .outerjoin(Comment, Comment.post_id == Post.post_id)\
         .filter(Post.user_id == user_id)\
         .group_by(db.func.date(Post.created_at))\
         .order_by(db.func.date(Post.created_at).desc())\
         .limit(30)\
         .all()
        
        result = []
        for date, posts_count, likes_count, comments_count in engagement_data:
            result.append({
                "date": date.isoformat() if date else None,
                "posts_count": int(posts_count),
                "likes_count": int(likes_count),
                "comments_count": int(comments_count)
            })
        
        return jsonify({"engagement_by_date": result}), 200
        
    except Exception as e:
        print(f"Error fetching engagement data: {str(e)}")
        return jsonify({"error": "Failed to fetch engagement data"}), 500
    
@posts_bp.route('/api/top-posts', methods=['GET'])
@jwt_required()
def get_top_posts():
    try:
        user_id = get_jwt_identity()
        
        # Get posts with most engagement
        top_posts = db.session.query(
            Post,
            User,
            db.func.count(distinct(Like.like_id)).label('likes_count'),
            db.func.count(distinct(Comment.comment_id)).label('comments_count'),
            (db.func.count(distinct(Like.like_id)) + 
             db.func.count(distinct(Comment.comment_id))).label('engagement_score')
        ).join(User, User.user_id == Post.user_id)\
         .outerjoin(Like, Like.post_id == Post.post_id)\
         .outerjoin(Comment, Comment.post_id == Post.post_id)\
         .group_by(Post.post_id, User.user_id)\
         .order_by(db.text('engagement_score DESC'))\
         .limit(10)\
         .all()
        
        result = []
        for post, author, likes_count, comments_count, engagement_score in top_posts:
            result.append({
                "post_id": post.post_id,
                "content": post.content,
                "created_at": post.created_at.isoformat(),
                "author": {
                    "user_id": author.user_id,
                    "username": author.username,
                    "name": author.name
                },
                "likes_count": int(likes_count),
                "comments_count": int(comments_count),
                "engagement_score": int(engagement_score)
            })
        
        return jsonify({"top_posts": result}), 200
        
    except Exception as e:
        print(f"Error fetching top posts: {str(e)}")
        return jsonify({"error": "Failed to fetch top posts"}), 500

@posts_bp.route('/<int:post_id>/comments', methods=['POST'])
@jwt_required()
def add_comment(post_id):
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        
        if not data or 'content' not in data:
            return jsonify({"error": "Comment content is required"}), 400
            
        # Check if post exists
        post = Post.query.get(post_id)
        if not post:
            return jsonify({"error": "Post not found"}), 404
            
        # Create new comment
        new_comment = Comment(
            content=data['content'],
            post_id=post_id,
            user_id=user_id,
            created_at=datetime.datetime.utcnow()  # Added explicit created_at
        )
        
        db.session.add(new_comment)
        db.session.commit()
        
        # Get author info for response
        author = User.query.get(user_id)
        
        return jsonify({
            "message": "Comment added successfully",
            "comment": {
                "comment_id": new_comment.comment_id,
                "content": new_comment.content,
                "created_at": new_comment.created_at.isoformat(),
                "author": {
                    "user_id": author.user_id,
                    "username": author.username,
                    "name": author.name
                }
            }
        }), 201
        
    except Exception as e:
        db.session.rollback()
        print(f"Error adding comment: {str(e)}")
        return jsonify({"error": "Failed to add comment"}), 500

@posts_bp.route('/api/stats', methods=['GET'])
@jwt_required()
def get_post_stats():
    try:
        user_id = get_jwt_identity()
        
        # Aggregate data: posts, likes, comments counts with averages
        stats = db.session.query(
            db.func.count(distinct(Post.post_id)).label('total_posts'),
            db.func.count(distinct(Like.like_id)).label('total_likes'),
            db.func.count(distinct(Comment.comment_id)).label('total_comments'),
            (db.func.count(distinct(Like.like_id)) / 
             db.func.nullif(db.func.count(distinct(Post.post_id)), 0)).label('avg_likes_per_post'),
            (db.func.count(distinct(Comment.comment_id)) / 
             db.func.nullif(db.func.count(distinct(Post.post_id)), 0)).label('avg_comments_per_post')
        ).outerjoin(Like, Like.post_id == Post.post_id)\
         .outerjoin(Comment, Comment.post_id == Post.post_id)\
         .filter(Post.user_id == user_id)\
         .first()
        
        return jsonify({
            "total_posts": int(stats.total_posts or 0),
            "total_likes": int(stats.total_likes or 0),
            "total_comments": int(stats.total_comments or 0),
            "average_likes_per_post": float(stats.avg_likes_per_post or 0),
            "average_comments_per_post": float(stats.avg_comments_per_post or 0)
        }), 200
        
    except Exception as e:
        print(f"Error fetching post stats: {str(e)}")
        return jsonify({"error": "Failed to fetch post statistics"}), 500

@posts_bp.route('/user', methods=['GET'])
def user_posts_page():
    return render_template('user_posts.html')

@posts_bp.route('/api/user', methods=['GET'])
@jwt_required()
def get_current_user_posts():
    try:
        user_id = get_jwt_identity()
        
        # Get user's posts
        user_posts = Post.query.filter_by(user_id=user_id)\
            .order_by(Post.created_at.desc())\
            .all()
        
        posts_data = []
        for post in user_posts:
            # Get likes count for the post
            likes_count = Like.query.filter_by(post_id=post.post_id).count()
            
            # Get comments for this post, ordered by created time
            comments = Comment.query.filter_by(post_id=post.post_id)\
                .order_by(Comment.created_at.asc()).all()
            
            comments_data = []
            for comment in comments:
                comment_author = User.query.get(comment.user_id)
                comments_data.append({
                    "comment_id": comment.comment_id,
                    "content": comment.content,
                    "created_at": comment.created_at.isoformat(),
                    "author": {
                        "user_id": comment_author.user_id,
                        "username": comment_author.username,
                        "name": comment_author.name
                    }
                })
            
            posts_data.append({
                "post_id": post.post_id,
                "content": post.content,
                "created_at": post.created_at.isoformat(),
                "likes_count": likes_count,
                "comments": comments_data
            })
        
        return jsonify({"posts": posts_data}), 200

    except Exception as e:
        print(f"Error fetching user posts: {str(e)}")
        return jsonify({"error": "Failed to fetch user posts"}), 500

@users_bp.route('/profile', methods=['GET'])
def profile_page():
    return render_template('profile.html')

@users_bp.route('/api/profile', methods=['GET'])
@jwt_required()
def show_user_profile():
    """Get current user's profile"""
    try:
        user_id = get_jwt_identity()
        print(f"User ID from JWT: {user_id}")  # Debugging

        user = User.query.get(user_id)
        if not user:
            return jsonify({"error": "User not found"}), 404

        # Get user's posts, followers, following counts
        posts = Post.query.filter_by(user_id=user_id).all()
        followers_count = Follower.query.filter_by(followed_user_id=user_id).count()
        following_count = Follower.query.filter_by(follower_user_id=user_id).count()

    except Exception as e:
        print(f"Error: {str(e)}")  # Debugging
        return jsonify({"error": "Unauthorized"}), 401

    
    return jsonify({
        "user_id": user.user_id,
        "username": user.username,
        "name": user.name,
        "email": user.email,
        "posts_count": len(posts),
        "followers_count": followers_count,
        "following_count": following_count
    }), 200

@users_bp.route('/api/profile/update', methods=['PUT'])
@jwt_required()
def update_user_profile():
    """Update current user's profile"""
    try:
        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        
        if not user:
            return jsonify({"error": "User not found"}), 404
        
        data = request.get_json()
        
        # Check if username is being updated and is unique
        new_username = data.get('username')
        if new_username and new_username != user.username:
            existing_user = User.query.filter_by(username=new_username).first()
            if existing_user:
                return jsonify({"error": "Username already taken"}), 400
            user.username = new_username
        
        # Check if email is being updated and is unique
        new_email = data.get('email')
        if new_email and new_email != user.email:
            existing_user = User.query.filter_by(email=new_email).first()
            if existing_user:
                return jsonify({"error": "Email already registered"}), 400
            user.email = new_email
        
        # Update name (no uniqueness constraint)
        new_name = data.get('name')
        if new_name:
            user.name = new_name
        
        # Commit changes to database
        db.session.commit()
        
        return jsonify({
            "message": "Profile updated successfully",
            "user_id": user.user_id,
            "username": user.username,
            "name": user.name,
            "email": user.email
        }), 200
        
    except Exception as e:
        print(f"Error updating profile: {str(e)}")
        return jsonify({"error": "Failed to update profile"}), 500


@users_bp.route('/<int:user_id>/profile', methods=['GET'])
@jwt_required()
def get_user_profile(user_id):
    try:
        user = User.query.get(user_id)
        
        if not user:
            return jsonify({"error": "User not found"}), 404
            
        # Get posts with join to count comments and likes
        posts_stats = db.session.query(
            Post,
            db.func.count(distinct(Comment.comment_id)).label('comment_count'),
            db.func.count(distinct(Like.like_id)).label('like_count')
        ).outerjoin(Comment, Comment.post_id == Post.post_id)\
         .outerjoin(Like, Like.post_id == Post.post_id)\
         .filter(Post.user_id == user_id)\
         .group_by(Post.post_id)\
         .all()
        
        # Count followers and following using joins
        followers = db.session.query(Follower, User)\
            .join(User, User.user_id == Follower.follower_user_id)\
            .filter(Follower.followed_user_id == user_id)\
            .all()
            
        following = db.session.query(Follower, User)\
            .join(User, User.user_id == Follower.followed_user_id)\
            .filter(Follower.follower_user_id == user_id)\
            .all()
        
        # Fix: Correctly unpack the 3 values from posts_stats
        total_likes = sum(like_count for _, _, like_count in posts_stats)
        total_comments = sum(comment_count for _, comment_count, _ in posts_stats)
        
        return jsonify({
            "user_id": user.user_id,
            "username": user.username,
            "name": user.name,
            "posts_count": len(posts_stats),
            "total_likes_received": total_likes,
            "total_comments_received": total_comments,
            "followers_count": len(followers),
            "following_count": len(following)
        }), 200
        
    except Exception as e:
        print(f"Error fetching user profile: {str(e)}")
        return jsonify({"error": "Failed to fetch user profile"}), 500
    

@users_bp.route('/<int:user_id>/follow/status', methods=['GET'])
@jwt_required()
def check_follow_status(user_id):
    try:
        current_user_id = get_jwt_identity()
        
        # Don't allow following yourself
        if int(current_user_id) == user_id:
            return jsonify({"is_following": False}), 200
            
        # Check if already following - FIXED: Changed field names
        is_following = Follower.query.filter_by(
            follower_user_id=current_user_id,
            followed_user_id=user_id
        ).first() is not None
        
        return jsonify({"is_following": is_following}), 200
        
    except Exception as e:
        print(f"Error checking follow status: {str(e)}")
        return jsonify({"error": "Failed to check follow status"}), 500

@users_bp.route('/<int:user_id>/follow', methods=['POST'])
@jwt_required() 
def toggle_follow(user_id):
    try:
        current_user_id = get_jwt_identity()
        
        # Don't allow following yourself
        if int(current_user_id) == user_id:
            return jsonify({"error": "You cannot follow yourself"}), 400
            
        # Check if target user exists
        target_user = User.query.get(user_id)
        if not target_user:
            return jsonify({"error": "User not found"}), 404
            
        # Check if already following - FIXED: Changed field names
        existing_follow = Follower.query.filter_by(
            follower_user_id=current_user_id,
            followed_user_id=user_id
        ).first()
        
        if existing_follow:
            # Unfollow
            db.session.delete(existing_follow)
            db.session.commit()
            return jsonify({"message": "User unfollowed successfully"}), 200
        else:
            # Follow - FIXED: Changed field names
            new_follow = Follower(follower_user_id=current_user_id, followed_user_id=user_id)
            db.session.add(new_follow)
            db.session.commit()
            return jsonify({"message": "User followed successfully"}), 201
            
    except Exception as e:
        db.session.rollback()
        print(f"Error toggling follow: {str(e)}")
        return jsonify({"error": "Failed to process follow request"}), 500

@users_bp.route('/<int:user_id>/posts', methods=['GET'])
@jwt_required()
def get_other_user_posts(user_id):  # RENAMED to avoid duplicate function name
    try:
        # Check if user exists
        user = User.query.get(user_id)
        if not user:
            return jsonify({"error": "User not found"}), 404
            
        # Get user's posts
        posts = Post.query.filter_by(user_id=user_id)\
            .order_by(Post.created_at.desc())\
            .limit(5).all()
            
        current_user_id = get_jwt_identity()
        
        posts_data = []
        for post in posts:
            # Count likes
            likes_count = Like.query.filter_by(post_id=post.post_id).count()
            # Check if current user liked this post
            user_liked = Like.query.filter_by(
                post_id=post.post_id, 
                user_id=current_user_id
            ).first() is not None
            
            posts_data.append({
                "post_id": post.post_id,
                "content": post.content,
                "created_at": post.created_at.isoformat(),
                "likes_count": likes_count,
                "user_liked": user_liked
            })
        
        return jsonify({"posts": posts_data}), 200
        
    except Exception as e:
        print(f"Error fetching user posts: {str(e)}")
        return jsonify({"error": "Failed to fetch user posts"}), 500
    

@users_bp.route('/followers', methods=['GET'])
def followers_page():
    return render_template('followers.html')

@users_bp.route('/api/followers', methods=['GET'])
@jwt_required()
def get_followers():
    """Get current user's followers"""
    try:
        user_id = get_jwt_identity()
        
        # Get followers with their details using join
        followers = db.session.query(User)\
            .join(Follower, User.user_id == Follower.follower_user_id)\
            .filter(Follower.followed_user_id == user_id)\
            .all()
            
        followers_data = []
        for follower in followers:
            followers_data.append({
                "user_id": follower.user_id,
                "username": follower.username,
                "name": follower.name
            })
        
        return jsonify({"followers": followers_data}), 200
        
    except Exception as e:
        print(f"Error fetching followers: {str(e)}")
        return jsonify({"error": "Failed to fetch followers"}), 500

@users_bp.route('/api/following', methods=['GET'])
@jwt_required()
def get_following():
    """Get users that the current user is following"""
    try:
        user_id = get_jwt_identity()
        
        # Get users the current user is following
        following = db.session.query(User)\
            .join(Follower, User.user_id == Follower.followed_user_id)\
            .filter(Follower.follower_user_id == user_id)\
            .all()
            
        following_data = []
        for followed_user in following:
            following_data.append({
                "user_id": followed_user.user_id,
                "username": followed_user.username,
                "name": followed_user.name
            })
        
        return jsonify({"following": following_data}), 200
        
    except Exception as e:
        print(f"Error fetching following users: {str(e)}")
        return jsonify({"error": "Failed to fetch following users"}), 500


