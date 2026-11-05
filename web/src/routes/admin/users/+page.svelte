<script lang="ts">
	import Planned from '#lib/admin/Planned.svelte';
</script>

<Planned
	title="Users"
	items={[
		'All users with their role and last login',
		'Creating users and resetting passwords (now: paperus user create)',
		'Making users administrators, deactivating and removing users'
	]}
/>
