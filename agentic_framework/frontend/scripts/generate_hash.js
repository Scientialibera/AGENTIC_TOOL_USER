// Usage: node scripts/generate_hash.js "YourPasswordHere"
const bcrypt = require('bcryptjs');

const password = process.argv[2];
if (!password) {
  console.error('Provide a password: node scripts/generate_hash.js "SuperSecret"');
  process.exit(1);
}

bcrypt.genSalt(12, (err, salt) => {
  if (err) throw err;
  bcrypt.hash(password, salt, (err2, hash) => {
    if (err2) throw err2;
    console.log('Password:', password);
    console.log('Hash:', hash);
  });
});
