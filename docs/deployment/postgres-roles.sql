\set ON_ERROR_STOP on
CREATE ROLE brandflow_app LOGIN PASSWORD :'business_password';
CREATE ROLE brandflow_checkpoint LOGIN PASSWORD :'checkpoint_password';
CREATE SCHEMA IF NOT EXISTS brandflow_checkpoint AUTHORIZATION brandflow_checkpoint;
ALTER ROLE brandflow_checkpoint IN DATABASE brandflow SET search_path TO brandflow_checkpoint;
GRANT CONNECT ON DATABASE brandflow TO brandflow_app, brandflow_checkpoint;
