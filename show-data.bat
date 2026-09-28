@echo off
REM Shows what ForiFlow has stored in PostgreSQL. Read-only: SELECTs only.
REM Needs the stack running (start.bat). Queries: scripts\show-data.sql
cd /d "%~dp0"
docker compose exec -T db sh -c "psql -U $POSTGRES_USER -d $POSTGRES_DB" < scripts\show-data.sql
echo.
docker volume inspect foriflow-pgdata --format "PostgreSQL data files: Docker volume {{.Name}} at {{.Mountpoint}} (inside Docker Desktop)"
echo.
pause
