import {afterEach,beforeEach,vi} from 'vitest';
import {cleanup} from '@testing-library/react';
afterEach(()=>{cleanup();vi.restoreAllMocks();vi.unstubAllGlobals();});
beforeEach(()=>{localStorage.clear();sessionStorage.clear();});
global.ResizeObserver=class {observe(){} unobserve(){} disconnect(){}};
global.URL.createObjectURL=()=> 'blob:test';
global.URL.revokeObjectURL=()=>{};
