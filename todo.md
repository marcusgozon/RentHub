RENTHUB WEBSITE - TO-DO LIST

PHASE 1: UI/UX IMPROVEMENTS
- Improve user profile UI and layout
- Add profile picture upload
- Add background photos to other pages
- Make website responsive on mobile, tablet, and desktop
- Improve login and signup UI
- Add success messages, error messages, and loading indicators
- Improve navigation bar and footer
- Make the design consistent across all pages

PHASE 2: DATABASE AND BACKEND
- Create MySQL database table for rental listings
- Store property information (title, description, address, price, condition)
- Store property image URLs
- Add tenant and landlord user roles
- Connect all forms to the Python Flask backend
- Save and retrieve data from MySQL
- Add edit and delete functions for listings
- Prevent duplicate email registration
- Secure login, logout, and user sessions
- Make sure landlords can only manage their own listings

PHASE 3: RENTAL LISTINGS
- Create a page for landlords to post rental properties
- Allow multiple photos per property
- Display rental details and monthly price
- Add available, occupied, and unavailable status
- Add search by location and price
- Add filters for property type and amenities
- Create a property details page
- Add sorting by price and newest listings
- Add listing reporting or approval features

PHASE 4: TENANT FEATURES
- Create tenant profile page
- Add favorites or saved listings
- Add rental inquiry or application form
- Allow tenants to contact landlords
- Add application status (pending, approved, rejected)
- Add reviews and ratings
- Add complaints and issue reports
- Add notifications for application updates

PHASE 5: LANDLORD FEATURES
- Create landlord dashboard
- View and manage posted properties
- View tenant inquiries and applications
- Manage property availability
- View rental history
- Manage tenant and payment records
- Add maintenance request management

PHASE 6: PAYMENTS AND RENTAL MANAGEMENT
- Create database tables for rental agreements and payments
- Record monthly rent, water, and electricity charges
- Add payment due dates and payment status
- Calculate overdue penalties based on agreed rules
- Allow tenants to submit payment references or receipts
- Let landlords verify and confirm payments
- Show payment history and outstanding balances
- Add reminders for upcoming and overdue payments
- Test payment calculations

PHASE 7: SECURITY AND TESTING
- Hash passwords securely
- Keep database passwords and secret keys out of GitHub
- Validate uploaded images and limit file sizes
- Protect tenant and landlord information
- Check user permissions on protected backend routes
- Enable HTTPS after deployment
- Test login, signup, duplicate emails, and logout
- Test different browsers and devices
- Test invalid forms and database errors
- Set up database backups
- Add privacy policy and terms of use

PHASE 8: HOSTING AND DEPLOYMENT
- Push project to GitHub
- Choose hosting for the Python backend
- Choose a hosted MySQL database
- Choose image storage for property photos
- Configure environment variables
- Deploy the Flask backend
- Deploy or serve the frontend
- Connect the live website to the hosted database
- Purchase or configure a domain name
- Enable HTTPS
- Test using school Wi-Fi and mobile data
- Set up database backups and error logging
- Prepare demo accounts and sample listings

PHASE 9: FINAL POLISH
- Add About Us and Contact pages
- Add FAQ and help section
- Add loading and error pages
- Remove test data and debugging code
- Check spelling, links, and page titles
- Optimize image sizes and loading speed
- Update README with setup instructions
- Prepare screenshots and documentation
- Prepare project presentation and live demo

RECOMMENDED PRIORITY ORDER
1. Finish login, signup, and user profiles
2. Create the rental listings database
3. Make landlord listing management functional
4. Connect property image uploads
5. Build tenant search and rental inquiries
6. Add rental agreements and payment tracking
7. Test security and permissions
8. Push to GitHub and deploy online
9. Polish the UI and prepare the final presentation