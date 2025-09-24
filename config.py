# Configuration settings
import os

class Config:
    SQLALCHEMY_DATABASE_URI = 'mysql://database:Mysql123@localhost/social_media_db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    JWT_SECRET_KEY = '57bfef66f643d42f184396eac87c4a9c58d0e59210c4fdea06341909c2ebb7b4'  
    DEBUG = True

class DevelopmentConfig(Config):
    DEBUG = True

class ProductionConfig(Config):
    DEBUG = False


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}