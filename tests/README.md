uses fixtures to build a dependency tree to test certain functionalities (since routes are not stateless, they depend on roles, which depend on jwt's)

At the start of the test run, it will teardown all of the tables in the remote supabase instance associated with the TESTING_DATABASE_URL conn str. THIS IS WHY YOU SHOULD NEVER PUT THE PROD LINK THERE!

Will simulate running HTTP through fastapi using pytest client, fixtures inject Account objects into test scopes to run further route tests