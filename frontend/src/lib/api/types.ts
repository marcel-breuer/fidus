export interface User {
	id: string;
	email: string;
	role: 'admin' | 'member';
	is_superuser: boolean;
}

export interface ModuleEntry {
	key: string;
	name_key: string;
	icon: string;
	route: string;
	scopes: string[];
}
