const API_BASE_URL = 'http://localhost:8000';

document.addEventListener('DOMContentLoaded', () => {
    // Handle Login
    const loginForm = document.getElementById('login-form');
    if (loginForm) {
        loginForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const username = document.getElementById('username').value;
            const password = document.getElementById('password').value;
            const errorDiv = document.getElementById('login-error');
            
            try {
                const response = await fetch(`${API_BASE_URL}/api/auth/login`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username, password })
                });
                
                const data = await response.json();
                
                if (response.ok) {
                    localStorage.setItem('sarvam_jwt', data.access_token);
                    localStorage.setItem('sarvam_username', data.username);
                    localStorage.setItem('sarvam_role', data.role);
                    window.location.href = 'index.html';
                } else {
                    errorDiv.innerText = data.detail || 'Login failed';
                    errorDiv.style.display = 'block';
                }
            } catch (err) {
                errorDiv.innerText = 'Network error. Backend might be down.';
                errorDiv.style.display = 'block';
            }
        });
    }

    // Handle Signup
    const signupForm = document.getElementById('signup-form');
    const otpForm = document.getElementById('otp-form');
    let pendingEmail = "";

    if (signupForm) {
        signupForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const username = document.getElementById('username').value;
            const email = document.getElementById('email').value;
            const password = document.getElementById('password').value;
            const role = document.querySelector('input[name="role"]:checked').value;
            
            const errorDiv = document.getElementById('signup-error');
            const successDiv = document.getElementById('signup-success');
            
            errorDiv.style.display = 'none';
            successDiv.style.display = 'none';
            
            try {
                // Change button text to show loading state
                const btn = signupForm.querySelector('button');
                const originalText = btn.innerText;
                btn.innerText = "Sending Code...";
                btn.disabled = true;

                const response = await fetch(`${API_BASE_URL}/api/auth/signup`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username, email, password, role })
                });
                
                const data = await response.json();
                btn.innerText = originalText;
                btn.disabled = false;
                
                if (response.ok && data.status === "pending_verification") {
                    pendingEmail = email;
                    signupForm.style.display = 'none';
                    otpForm.style.display = 'block';
                } else {
                    errorDiv.innerText = data.detail || 'Signup failed';
                    errorDiv.style.display = 'block';
                }
            } catch (err) {
                errorDiv.innerText = 'Network error. Backend might be down.';
                errorDiv.style.display = 'block';
            }
        });
    }

    // Handle OTP Verification
    if (otpForm) {
        otpForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const otpCode = document.getElementById('otp-code').value;
            const errorDiv = document.getElementById('signup-error');
            const successDiv = document.getElementById('signup-success');
            
            errorDiv.style.display = 'none';
            
            try {
                const response = await fetch(`${API_BASE_URL}/api/auth/verify-otp`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email: pendingEmail, otp: otpCode })
                });
                
                const data = await response.json();
                
                if (response.ok) {
                    successDiv.innerText = "Account verified! Redirecting...";
                    successDiv.style.display = 'block';
                    localStorage.setItem('sarvam_jwt', data.access_token);
                    localStorage.setItem('sarvam_username', data.username);
                    localStorage.setItem('sarvam_role', data.role);
                    setTimeout(() => {
                        window.location.href = 'index.html';
                    }, 1500);
                } else {
                    errorDiv.innerText = data.detail || 'Verification failed';
                    errorDiv.style.display = 'block';
                }
            } catch (err) {
                errorDiv.innerText = 'Network error. Backend might be down.';
                errorDiv.style.display = 'block';
            }
        });
    }
});
