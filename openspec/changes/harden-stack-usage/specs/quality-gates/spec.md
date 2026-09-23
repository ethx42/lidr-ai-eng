## ADDED Requirements

### Requirement: Runtime dependencies declared
Every third-party package imported by application code SHALL be installed by the runtime dependency set alone, so a production install without development dependencies can start the application. The test suite SHALL verify this.

#### Scenario: Import provided only by a dev dependency
- **WHEN** application code imports a package that only the development dependency group installs
- **THEN** the dependency test fails naming that package

### Requirement: Reproducible toolchain
The project SHALL pin the range of package-manager versions it supports in its project configuration, so local runs and CI use a compatible package manager. CI SHALL refuse to update the lockfile implicitly during any step, not only during install. The test suite SHALL verify that both settings are present.

#### Scenario: Lockfile out of date in CI
- **WHEN** `pyproject.toml` changes without a matching `uv.lock` update
- **THEN** the CI run fails instead of re-locking

#### Scenario: Pin removed
- **WHEN** the package-manager version pin is removed from the project configuration
- **THEN** the toolchain test fails
