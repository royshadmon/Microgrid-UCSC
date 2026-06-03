// // Simple test file for file_auth.js service
// // This can be run in the browser console to test the service

// // Test the file_auth service
// async function testFileAuth() {
//     console.log('Testing File Auth Service...');
    
//     try {
//         // Test 1: Signup
//         console.log('1. Testing signup...');
//         const signupResult = await signup({
//             email: `test_${Date.now()}@example.com`,
//             password: 'password123',
//             firstName: 'Test',
//             lastName: 'User'
//         });
//         console.log('✅ Signup successful:', signupResult);
        
//         // Test 2: Login
//         console.log('2. Testing login...');
//         const loginResult = await login({
//             email: signupResult.data.user.email,
//             password: 'password123'
//         });
//         console.log('✅ Login successful:', loginResult);
        
//         // Test 3: Get user
//         console.log('3. Testing get user...');
//         const userResult = await getUser();
//         console.log('✅ Get user successful:', userResult);
        
//         // Test 4: Add bookmark
//         console.log('4. Testing add bookmark...');
//         const bookmarkResult = await bookmarkNode({ node: 'test-node:8080' });
//         console.log('✅ Bookmark added:', bookmarkResult);
        
//         // Test 5: Get bookmarks
//         console.log('5. Testing get bookmarks...');
//         const bookmarksResult = await getBookmarks();
//         console.log('✅ Get bookmarks successful:', bookmarksResult);
        
//         // Test 6: Add preset group
//         console.log('6. Testing add preset group...');
//         const groupResult = await addPresetGroup({ name: 'Test Group' });
//         console.log('✅ Preset group added:', groupResult);
        
//         // Test 7: Get preset groups
//         console.log('7. Testing get preset groups...');
//         const groupsResult = await getPresetGroups();
//         console.log('✅ Get preset groups successful:', groupsResult);
        
//         // Test 8: Add preset
//         console.log('8. Testing add preset...');
//         const presetResult = await addPreset({
//             preset: {
//                 group_id: groupResult.data.group.id,
//                 command: 'test command',
//                 type: 'GET',
//                 button: 'Test Button'
//             }
//         });
//         console.log('✅ Preset added:', presetResult);
        
//         // Test 9: Get presets by group
//         console.log('9. Testing get presets by group...');
//         const presetsResult = await getPresetsByGroup({
//             groupId: groupResult.data.group.id
//         });
//         console.log('✅ Get presets successful:', presetsResult);
        
//         console.log('🎉 All tests passed!');
        
//     } catch (error) {
//         console.error('❌ Test failed:', error);
//     }
// }

// // Export for use in browser console
// if (typeof window !== 'undefined') {
//     window.testFileAuth = testFileAuth;
// }

// export { testFileAuth }; 