import { ComponentFixture, TestBed } from '@angular/core/testing';

import { Constructor } from './constructor';

describe('Constructor', () => {
  let component: Constructor;
  let fixture: ComponentFixture<Constructor>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [Constructor]
    })
    .compileComponents();

    fixture = TestBed.createComponent(Constructor);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
