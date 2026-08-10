# Help Cat Domain and Production Release Plan

**Goal:** Ship the reviewed Help Cat community-governance release, bind `helpcat.xyz` and `www.helpcat.xyz` to `175.178.41.19`, and enable trusted HTTPS without disrupting unrelated services.

## Release gates

1. Run Python, Node, JavaScript syntax, migration, and diff checks.
2. Commit and push the reviewed source and Wiki documentation through ClashX.
3. Back up the production database, application release, static assets, and Nginx configuration.
4. Upload a checksummed release, migrate the copied/production database through Alembic `003_scale_integrity`, and restart only `help-cat.service`.
5. Deploy the responsive H5 and administrator UI while preserving the legacy IP URL.
6. Create Alibaba Cloud DNS A records for `@` and `www` to `175.178.41.19`.
7. Configure Nginx for both hostnames and both `/api/` and `/help-cat-api/` routes; issue a free automatically renewed TLS certificate and redirect HTTP to HTTPS.
8. Verify health, authentication/roles, community and cat linked-review flows, uploads, responsive layouts, certificate validity, and legacy URL compatibility.
9. Record the release, rollback points, domain configuration, and remaining mini-program work in the repository Wiki.

## Rollback

- Restore the timestamped SQLite backup and previous `/opt/help-cat/release` directory.
- Restore the timestamped Nginx configuration and reload Nginx after `nginx -t` succeeds.
- DNS records can be changed back independently; unrelated services are never stopped.
