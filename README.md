# group_project_490_backend

Backend for 'Till Failure

Run with `python -m src.api.app`
You can view api docs, and run routes with UI by going to `http://localhost:9090/docs`

To test out most endpoints, you need to create an account, most routes are protected in the role system, you must first create an account in the /auth category, then you can authorize yourself in the top right corner with the unm/pw; passwords are hashed as soon as the info comes in.

JWT's need to be handled client side with auth/login to get jwt for bearer token using the API thru fetch or axios.

Hi I'm redeploying