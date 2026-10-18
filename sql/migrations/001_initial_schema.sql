-- 001: initial schema for the GitHub snapshot.
-- Keys are GitHub's own ids/numbers so re-running the collector updates rows instead of duplicating them.
-- No issue/comment body text is stored in v1.

CREATE TABLE repos (
    id                  bigint PRIMARY KEY,          
    full_name           text NOT NULL UNIQUE,        
    description         text,                       
    topics              text[] NOT NULL DEFAULT '{}', 
    homepage            text,                        
    html_url            text NOT NULL,              
    stars               integer NOT NULL,
    forks               integer NOT NULL,
    open_issues         integer NOT NULL,           
    language            text,
    license             text,                       
    archived            boolean NOT NULL,
    created_at          timestamptz NOT NULL,
    pushed_at           timestamptz,
    has_readme          boolean,
    has_contributing    boolean,
    has_code_of_conduct boolean,
    snapshot_at         timestamptz NOT NULL        
);

CREATE TABLE issues (
    repo_id            bigint NOT NULL REFERENCES repos (id),
    number             integer NOT NULL,
    is_pull_request    boolean NOT NULL,
    state              text NOT NULL CHECK (state IN ('open', 'closed')),
    state_reason       text,                        
    author_login       text,
    author_association text NOT NULL,
    labels             text[] NOT NULL DEFAULT '{}', 
    created_at         timestamptz NOT NULL,
    closed_at          timestamptz,
    updated_at         timestamptz NOT NULL,
    PRIMARY KEY (repo_id, number)
);
CREATE INDEX issues_repo_created_idx ON issues (repo_id, created_at);

CREATE TABLE comments (
    id                 bigint PRIMARY KEY,           
    repo_id            bigint NOT NULL REFERENCES repos (id),
    issue_number       integer NOT NULL,
    author_login       text,
    author_association text NOT NULL,
    created_at         timestamptz NOT NULL
);
CREATE INDEX comments_issue_created_idx ON comments (repo_id, issue_number, created_at);

CREATE TABLE pull_requests (
    repo_id    bigint NOT NULL REFERENCES repos (id),
    number     integer NOT NULL,
    is_draft   boolean NOT NULL,
    merged_at  timestamptz,
    base_ref   text NOT NULL,                       
    PRIMARY KEY (repo_id, number)
);

CREATE TABLE reviews (
    id                 bigint PRIMARY KEY,           
    repo_id            bigint NOT NULL REFERENCES repos (id),
    pr_number          integer NOT NULL,
    reviewer_login     text,
    author_association text NOT NULL,
    state              text NOT NULL,               
    submitted_at       timestamptz                  
);
CREATE INDEX reviews_pr_submitted_idx ON reviews (repo_id, pr_number, submitted_at);

CREATE TABLE releases (
    id            bigint PRIMARY KEY,                
    repo_id       bigint NOT NULL REFERENCES repos (id),
    tag           text NOT NULL,
    is_prerelease boolean NOT NULL,
    is_draft      boolean NOT NULL,
    published_at  timestamptz                        
);

CREATE TABLE commits (
    repo_id      bigint NOT NULL REFERENCES repos (id),
    sha          text NOT NULL,
    author_login text,                               
    committed_at timestamptz NOT NULL,
    PRIMARY KEY (repo_id, sha)
);
CREATE INDEX commits_repo_committed_idx ON commits (repo_id, committed_at);

CREATE TABLE sync_runs (
    id             bigserial PRIMARY KEY,
    repo_full_name text NOT NULL,
    started_at     timestamptz NOT NULL DEFAULT now(),
    finished_at    timestamptz,
    status         text NOT NULL CHECK (status IN ('running', 'success', 'failed')),
    requests_used  integer,
    error          text
);
